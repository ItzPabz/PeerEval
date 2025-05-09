from django.db.models import Avg, F
from src.models import MeritScores, Evaluations

def get_flags(student_id, assignment_id):
    peer_evals = Evaluations.objects.filter(
        evaluatee_id=student_id,
        assignment_id=assignment_id
    ).exclude(evaluator_id=student_id)

    peer_scores = MeritScores.objects.filter(
        evaluation_id__in=peer_evals
    ).annotate(
        avg_score=(
            F('score_workcontribution') + 
            F('score_teaminteraction') +
            F('score_teamawareness') +
            F('score_qualityofwork') +
            F('score_knowledgeandskills')
        ) / 5.0
    )

    peer_avg = peer_scores.aggregate(avg_peer_rating=Avg('avg_score'))['avg_peer_rating']

    team_scores = MeritScores.objects.filter(
        evaluation_id__assignment_id=assignment_id
    ).exclude(
        evaluation_id__evaluator_id=student_id
    ).annotate(
        avg_score=(
            F('score_workcontribution') + 
            F('score_teaminteraction') +
            F('score_teamawareness') +
            F('score_qualityofwork') +
            F('score_knowledgeandskills')
        ) / 5.0
    )
    team_avg = team_scores.aggregate(avg_team_rating=Avg('avg_score'))['avg_team_rating']

    self_eval = Evaluations.objects.filter(
        evaluator_id=student_id,
        evaluatee_id=student_id,
        assignment_id=assignment_id
    ).first()

    self_score = None
    if self_eval:
        self_merit = MeritScores.objects.filter(evaluation_id=self_eval).first()
        if self_merit:
            self_score = (
                self_merit.score_workcontribution +
                self_merit.score_teaminteraction +
                self_merit.score_teamawareness +
                self_merit.score_qualityofwork +
                self_merit.score_knowledgeandskills
            ) / 5.0

    flags = []

    if peer_avg and peer_avg < 2.5:
        flags.append({
            'type': 'error',
            'label': 'Low Performer',
            'instructor_msg': 'Student is performing below expectations with average rating < 2.5',
        })

    if self_score and peer_avg and (self_score - peer_avg) >= 1.0 and peer_avg < 3:
        flags.append({
            'type': 'warning',
            'label': 'Overconfident',
            'instructor_msg': 'Student rated themselves significantly higher than peer ratings',
        })

    if peer_avg and peer_avg > 3.5 and team_avg and (peer_avg - team_avg) > 0.5:
        flags.append({
            'type': 'success',
            'label': 'High Performer',
            'instructor_msg': 'Student is performing exceptionally well with ratings significantly above team average',
        })

    if self_score and peer_avg and (peer_avg - self_score) >= 1.0 and peer_avg > 3:
        flags.append({
            'type': 'info',
            'label': 'Underconfident',
            'instructor_msg': 'Student rated themselves significantly lower than peer ratings',
        })

    if self_score and self_score >= 4:
        team_ratings = MeritScores.objects.filter(
            evaluation_id__evaluator_id=student_id,
            evaluation_id__assignment_id=assignment_id
        ).exclude(
            evaluation_id__evaluatee_id=student_id
        ).annotate(
            avg_score=(
                F('score_workcontribution') + 
                F('score_teaminteraction') +
                F('score_teamawareness') +
                F('score_qualityofwork') +
                F('score_knowledgeandskills')
            ) / 5.0
        )
        
        team_ratings_list = [r.avg_score for r in team_ratings if r.avg_score is not None]
        if team_ratings_list and all(r <= (self_score - 2) for r in team_ratings_list):
            flags.append({
                'type': 'error',
                'label': 'Manipulator',
                'instructor_msg': 'Student rated themselves high while rating others significantly lower',
            })

    for eval in peer_evals:
        peer_rating = MeritScores.objects.filter(evaluation_id=eval).first()
        if not peer_rating:
            continue
            
        peer_rating_avg = (
            peer_rating.score_workcontribution +
            peer_rating.score_teaminteraction +
            peer_rating.score_teamawareness +
            peer_rating.score_qualityofwork +
            peer_rating.score_knowledgeandskills
        ) / 5.0

        if peer_rating_avg <= 2:
            others = peer_evals.exclude(evaluator_id=eval.evaluator_id)
            if others.count() >= 2:
                other_scores = MeritScores.objects.filter(
                    evaluation_id__in=others
                ).annotate(
                    avg_score=(
                        F('score_workcontribution') + 
                        F('score_teaminteraction') +
                        F('score_teamawareness') +
                        F('score_qualityofwork') +
                        F('score_knowledgeandskills')
                    ) / 5.0
                )
                median = sorted([s.avg_score for s in other_scores if s.avg_score is not None])
                if median:
                    median_score = median[len(median) // 2]
                    if median_score >= 3:
                        flags.append({
                            'type': 'warning',
                            'label': 'Conflict',
                            'instructor_msg': f'Potential conflict between student and {eval.evaluator_id.username}',
                        })
                        break
    return flags


