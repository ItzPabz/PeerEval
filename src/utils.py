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

    if peer_avg and peer_avg > 3.5:
        flags.append("High Contribution")

    if self_score and peer_avg and (peer_avg - self_score) >= 1.0:
        flags.append("Underconfident")

    if peer_avg and peer_avg < 2.5:
        flags.append("Low Contribution")

    if self_score and peer_avg and (self_score - peer_avg) >= 1.0 and peer_avg < 3:
        flags.append("Overconfident")

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

        others = peer_evals.exclude(evaluator_id=eval.evaluator_id)
        if others.count() >= 2:
            other_scores = MeritScores.objects.filter(evaluation_id__in=others).annotate(
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
                if peer_rating_avg <= 2 and median_score >= 3:
                    flags.append("Evaluation Mismatch")
                    break

    return flags


