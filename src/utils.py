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

    # Get team average (excluding self)
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

    # Low Performer
    if peer_avg and peer_avg < 2.5:
        flags.append({
            'type': 'error',
            'label': 'Low Performer',
            'instructor_msg': 'Student is performing below expectations with average rating < 2.5',
            'student_msg': 'The members of your team indicated that your contributions to the team were below expectations. This report gives you details about how the members of your team perceived your team contributions in five key areas. Please use this information to identify problem areas in order to contribute effectively in future teamwork situations. Please contact your course instructor if you need assistance or if you believe that your ratings were inappropriate.'
        })

    # Overconfident
    if self_score and peer_avg and (self_score - peer_avg) >= 1.0 and peer_avg < 3:
        flags.append({
            'type': 'warning',
            'label': 'Overconfident',
            'instructor_msg': 'Student rated themselves significantly higher than peer ratings',
            'student_msg': 'Your self-ratings were significantly higher than your teammates\' ratings of your contributions to the team. The members of your team indicated that your contributions to the team were below expectations. This report gives you details about how the members of your team perceived your team contributions in five key areas. Please use this information to identify problem areas in order to contribute effectively in future teamwork situations. Please contact your course instructor if you need assistance or if you believe that your ratings were inappropriate.'
        })

    # High Performer
    if peer_avg and peer_avg > 3.5 and team_avg and (peer_avg - team_avg) > 0.5:
        flags.append({
            'type': 'success',
            'label': 'High Performer',
            'instructor_msg': 'Student is performing exceptionally well with ratings significantly above team average',
            'student_msg': 'Congratulations! The members of your team have indicated that you were a highly effective team member. Keep up the good work!'
        })

    # Underconfident
    if self_score and peer_avg and (peer_avg - self_score) >= 1.0 and peer_avg > 3:
        flags.append({
            'type': 'info',
            'label': 'Underconfident',
            'instructor_msg': 'Student rated themselves significantly lower than peer ratings',
            'student_msg': 'Your self-ratings were significantly lower than your teammates\' ratings of your contributions to the team. The members of your team have indicated that you were a highly effective team member. Please try not to minimize the value of your contributions to the team.'
        })

    # Manipulator
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
                'student_msg': 'Your self-evaluation indicates you made the primary contribution to the project with little value added by your teammates. The ratings from your teammates did not concur with your assessment. Your instructor may require additional information to clarify what happened in your team.'
            })

    # Conflict
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
                            'instructor_msg': f'Potential conflict between student and evaluator {eval.evaluator_id.username}',
                            'student_msg': 'Your evaluation indicates significant disagreement with other team members\' assessments. Your instructor may require additional information to clarify what happened in your team.'
                        })
                        break

    return flags


