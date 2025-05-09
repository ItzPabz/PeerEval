from django.shortcuts import render, redirect, get_object_or_404
from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from functools import wraps
from src.models import Users, Enrollments, Sections, Assignments, Courses, Evaluations, Departments, SectionInstructors, MeritScores, Terms, Groups
from django.utils import timezone
from django.db import models
from src.forms import CourseForm, InstructorForm, SectionForm, AssignmentForm, StudentForm, SectionAddStudentForm, SectionAddAssignmentForm, GroupFormationMethodForm, PasswordResetRequestForm, PasswordResetForm, LoginForm, AssignmentEditForm, SectionAddInstructorForm, TermForm
from django.db.models import Q
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.views import LogoutView
from django.http import HttpResponse
from django.conf import settings
from src.utils import get_flags
import csv
from datetime import datetime
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
import re

def rate_limit_login(username):
    cache_key = f"login_attempts_{username}"
    attempts = cache.get(cache_key, 0)
    
    if attempts >= 5:
        return False
        
    cache.set(cache_key, attempts + 1, 300)
    return True

@login_required
def index(request):
    current_user = request.user
    search_query = request.GET.get('search', '')
    page_number = request.GET.get('page', 1)
    now = timezone.now()
    
    if current_user.is_instructor:
        active_sections = Sections.get_active_sections_for_instructor(current_user).annotate(
            student_count=models.Count('enrollments', distinct=True),
            assignment_count=models.Count('assignments', distinct=True)
        )
        past_sections = Sections.get_past_sections_for_instructor(current_user).annotate(
            student_count=models.Count('enrollments', distinct=True),
            assignment_count=models.Count('assignments', distinct=True)
        )
        active_students = Enrollments.objects.filter(
            section_id__in=active_sections,
            section_id__term__end_date__gte=timezone.now().date()
        ).select_related('user_id', 'section_id', 'section_id__course', 'section_id__term')
        past_students = Enrollments.objects.filter(
            section_id__in=Sections.get_past_sections_for_instructor(current_user),
            section_id__term__end_date__lt=timezone.now().date()
        ).select_related('user_id', 'section_id', 'section_id__course', 'section_id__term')
        active_assignments = Assignments.objects.filter(
            section_id__in=active_sections,
            section_id__term__end_date__gte=timezone.now().date()
        ).select_related('section_id', 'section_id__course', 'section_id__term')
        active_evaluations = Evaluations.objects.filter(
            assignment_id__section_id__in=active_sections,
            assignment_id__section_id__term__end_date__gte=timezone.now().date()
        ).select_related('assignment_id', 'assignment_id__section_id', 'assignment_id__section_id__course', 'assignment_id__section_id__term')
        past_evaluations = Evaluations.objects.filter(
            evaluator_id=current_user
        ).select_related(
            'assignment_id',
            'assignment_id__section_id',
            'assignment_id__section_id__course',
            'assignment_id__section_id__course__department',
            'assignment_id__section_id__term',
            'evaluatee_id'
        ).order_by('-submission_date')
        
        if search_query:
            past_evaluations = past_evaluations.filter(
                Q(assignment_id__name__icontains=search_query) |
                Q(evaluatee_id__first_name__icontains=search_query) |
                Q(evaluatee_id__last_name__icontains=search_query) |
                Q(assignment_id__section_id__course__department__id__icontains=search_query) |
                Q(assignment_id__section_id__course__course_code__icontains=search_query)
            )

        paginator = Paginator(past_evaluations, 10)
        try:
            past_evaluations_page = paginator.page(page_number)
        except PageNotAnInteger:
            past_evaluations_page = paginator.page(1)
        except EmptyPage:
            past_evaluations_page = paginator.page(paginator.num_pages)
        
        for evaluation in past_evaluations_page:
            evaluation.assignment_id.assignment_active = (
                evaluation.assignment_id.available_date <= now and 
                evaluation.assignment_id.due_date >= now
            )

        def calculate_alert_level(assignment):
            time_until_due = (assignment.due_date - now).total_seconds()
            
            if time_until_due <= 3600:
                return 'red'
            elif time_until_due <= 86400:
                return 'yellow'
            elif assignment.available_date <= now and assignment.due_date >= now:
                return 'green'
            else:
                return 'gray'   
                
        assignments = active_assignments
        for assignment in assignments:
            assignment.assignment_active = assignment.available_date <= now and assignment.due_date >= now
            assignment.alert_level = calculate_alert_level(assignment)

        total_students = active_students.count()
        total_assignments = active_assignments.count()
        total_evaluations = active_evaluations.count()
        
        avg_students_per_section = active_sections.aggregate(
            avg=models.Avg('student_count')
        )['avg'] or 0
        
        avg_assignments_per_section = active_sections.aggregate(
            avg=models.Avg('assignment_count')
        )['avg'] or 0
                
        total_possible_evaluations = sum(
            section.student_count * section.assignment_count 
            for section in active_sections
        )
        evaluation_completion_rate = total_possible_evaluations and (total_evaluations / total_possible_evaluations * 100) or 0

        current_term = active_sections.first().term if active_sections.exists() else None
        if current_term:
            all_active_sections = Sections.objects.filter(
                term=current_term
            ).annotate(
                student_count=models.Count('enrollments', distinct=True),
                assignment_count=models.Count('assignments', distinct=True)
            )

            instructor_sections = all_active_sections.filter(
                sectioninstructors__user_id=current_user
            )

            coordinator_sections = all_active_sections.filter(
                course__coordinator=current_user
            )

            accessible_sections = instructor_sections | coordinator_sections

            active_courses = Courses.objects.filter(
                sections__in=accessible_sections
            ).prefetch_related(
                models.Prefetch(
                    'sections',
                    queryset=accessible_sections,
                    to_attr='active_sections'
                )
            ).select_related('department').distinct()
        else:
            active_courses = Courses.objects.none()

        past_terms = Terms.objects.filter(
            end_date__lt=timezone.now().date()
        ).order_by('-end_date')

        past_terms_data = []
        for term in past_terms:
            term_sections = past_sections.filter(term=term)
            term_courses = Courses.objects.filter(
                sections__in=term_sections
            ).prefetch_related(
                models.Prefetch(
                    'sections',
                    queryset=term_sections,
                    to_attr='term_sections'
                )
            ).select_related('department').distinct()
            
            if term_courses.exists():
                past_terms_data.append({
                    'name': term.name,
                    'courses': term_courses
                })

        is_depthead = Departments.objects.filter(department_head=current_user.id).exists()
        try:
            department = Departments.objects.get(department_head=current_user.id) if is_depthead else None
        except Departments.DoesNotExist:
            department = None
            
        is_coordinator = Courses.objects.filter(coordinator=current_user.id).exists()
        courses_coordinated = Courses.objects.filter(coordinator=current_user.id)
        is_instructor = SectionInstructors.objects.filter(user_id=current_user.id).exists()
        sections_instructed = SectionInstructors.objects.filter(user_id=current_user.id)
        is_superuser = current_user.is_superuser

        all_students = Enrollments.objects.filter(
            user_id__in=active_students.values_list('user_id', flat=True).distinct() | 
            past_students.values_list('user_id', flat=True).distinct()
        ).select_related('user_id').order_by('user_id__last_name', 'user_id__first_name')

        context = {
            'stats': {
                'courses': {
                    'value': active_courses.count(),
                    'desc': f'Across {active_sections.count()} sections'
                },
                'sections': {
                    'value': active_sections.count(),
                    'desc': f'Avg {avg_students_per_section:.1f} students per section'
                },
                'assignments': {
                    'value': total_assignments,
                    'desc': f'Avg {avg_assignments_per_section:.1f} per section'
                },
                'students': {
                    'value': total_students,
                    'desc': f'Active in {active_sections.count()} sections'
                },
                'evaluations': {
                    'value': total_evaluations,
                    'desc': f'Completion rate: {evaluation_completion_rate:.1f}%'
                }
            },
            'active_courses': active_courses,
            'past_terms': past_terms_data,
            'is_superuser': is_superuser,
            'is_depthead': is_depthead,
            'is_coordinator': is_coordinator,
            'is_instructor': is_instructor,
            'instructor_students': all_students,
            'departments': Departments.objects.all().order_by('name'),
            'instructors': Users.objects.filter(is_instructor=True).order_by('last_name', 'first_name'),
            'terms': Terms.objects.filter(end_date__gte=timezone.now().date()).order_by('start_date'),
            'courses': courses_coordinated if is_coordinator else Courses.objects.none(),
            'department_prefixes': {
                'pattern': '|'.join(Departments.objects.values_list('id', flat=True)),
                'display': ', '.join(Departments.objects.values_list('id', flat=True))
            }
        }
        return render(request, 'instructor/dashboard.html', context)
    else:
        now = timezone.now()
        enrollments = Enrollments.objects.filter(
            user_id=current_user
        ).select_related(
            'section_id',
            'section_id__course',
            'section_id__term',
            'section_id__course__department',
            'group'
        ).order_by('-section_id__term__start_date')
        
        assignments = Assignments.objects.filter(
            section_id__in=Sections.objects.filter(
                enrollments__user_id=current_user.id
            ),
            due_date__gte=timezone.now()
        ).exclude(
            evaluations__evaluator_id=current_user.id
        ).select_related(
            'section_id',
            'section_id__course',
            'section_id__term'
        ).order_by('due_date').distinct()

        search_query = request.GET.get('search', '')
        page_number = request.GET.get('page', 1)
        
        past_evaluations = Evaluations.objects.filter(
            evaluator_id=current_user
        ).select_related(
            'assignment_id',
            'assignment_id__section_id',
            'assignment_id__section_id__course',
            'assignment_id__section_id__course__department',
            'assignment_id__section_id__term',
            'evaluatee_id'
        ).order_by('-submission_date')
        
        if search_query:
            past_evaluations = past_evaluations.filter(
                Q(assignment_id__name__icontains=search_query) |
                Q(evaluatee_id__first_name__icontains=search_query) |
                Q(evaluatee_id__last_name__icontains=search_query) |
                Q(assignment_id__section_id__course__department__id__icontains=search_query) |
                Q(assignment_id__section_id__course__course_code__icontains=search_query)
            )

        paginator = Paginator(past_evaluations, 10)
        try:
            past_evaluations_page = paginator.page(page_number)
        except PageNotAnInteger:
            past_evaluations_page = paginator.page(1)
        except EmptyPage:
            past_evaluations_page = paginator.page(paginator.num_pages)
        
        for evaluation in past_evaluations_page:
            evaluation.assignment_id.assignment_active = (
                evaluation.assignment_id.available_date <= now and 
                evaluation.assignment_id.due_date >= now
            )

        def calculate_alert_level(assignment):
            time_until_due = (assignment.due_date - now).total_seconds()
            
            if time_until_due <= 3600:
                return 'red'
            elif time_until_due <= 86400:
                return 'yellow'
            elif assignment.available_date <= now and assignment.due_date >= now:
                return 'green'
            else:
                return 'gray'   
                
        for assignment in assignments:
            assignment.assignment_active = assignment.available_date <= now and assignment.due_date >= now
            assignment.alert_level = calculate_alert_level(assignment)

        context = {
            'user': current_user,
            'enrollments': enrollments,
            'assignments': assignments,
            'past_evaluations': past_evaluations_page,
            'search_query': search_query,
            'now': now
        }
        return render(request, 'student/dashboard.html', context)

@login_required
def evaluation(request, department, course, section_number, assignment):
    user = request.user
    
    assignment = Assignments.objects.select_related(
        'section_id',
        'section_id__course',
        'section_id__course__department'
    ).get(id=assignment)
    
    existing_evaluations = Evaluations.objects.filter(
        assignment_id=assignment,
        evaluator_id=user
    )
    
    if existing_evaluations.exists():
        messages.warning(request, 'Peer Eval already submitted')
        return redirect('index')
        
    enrollment = Enrollments.objects.select_related('group').get(
        user_id=user,
        section_id=assignment.section_id
    )
    group_members = []
    if enrollment.group and assignment.self_eval:
        group_members = [enrollment]
        group_members.extend(
            Enrollments.objects.select_related('user_id').filter(
                group=enrollment.group
            ).exclude(user_id=user)
        )
    elif enrollment.group:
        group_members = Enrollments.objects.select_related('user_id').filter(
            group=enrollment.group
        ).exclude(user_id=user)
    
    context = {
        'assignment': assignment,
        'user': user,
        'group_members': group_members,
        'self_eval_enabled': assignment.self_eval,
        'merits_enabled': assignment.enable_merits,
        'existing_evaluations': existing_evaluations,
        'department': assignment.section_id.course.department,
        'course': assignment.section_id.course,
        'section_number': section_number
    }
    return render(request, 'student/evaluation.html', context)

@login_required
def submit_evaluation(request, department, course, section_number, assignment):
    if request.method != 'POST':
        return redirect('evaluation', department=department, course=course, section_number=section_number, assignment=assignment)
        
    evaluator = request.user
    
    try:
        assignment_obj = Assignments.objects.get(id=assignment)
        
        existing_evaluations = Evaluations.objects.filter(
            assignment_id=assignment_obj,
            evaluator_id=evaluator
        )
        
        if existing_evaluations.exists():
            messages.error(request, 'Peer Eval already submitted')
            return redirect('evaluation', department=department, course=course, section_number=section_number, assignment=assignment)
            
        enrollment = Enrollments.objects.select_related('group').get(
            user_id=evaluator,
            section_id=assignment_obj.section_id
        )
        
        group_members = []
        if enrollment.group and assignment_obj.self_eval:
            group_members = [enrollment]
            group_members.extend(
                Enrollments.objects.select_related('user_id').filter(
                    group=enrollment.group
                ).exclude(user_id=evaluator)
            )
        elif enrollment.group:
            group_members = Enrollments.objects.select_related('user_id').filter(
                group=enrollment.group
            ).exclude(user_id=evaluator)
        total_points = 0
        for i in range(1, len(group_members) + 1):
            points = request.POST.get(f'points_{i}')
            if points:
                try:
                    points = int(points)
                    total_points += points
                except ValueError:
                    messages.error(request, f'Invalid points value for member {i}')
                    return redirect('evaluation', department=department, course=course, section_number=section_number, assignment=assignment)

        max_total_points = assignment_obj.max_points_self * len(group_members)
        if total_points > max_total_points:
            messages.error(request, f'Total points ({total_points}) cannot exceed maximum allowed ({max_total_points})')
            return redirect('evaluation', department=department, course=course, section_number=section_number, assignment=assignment)
            
        for i in range(1, len(group_members) + 1):
            evaluated_index = request.POST.get(f'evaluated_index_{i}')
            if not evaluated_index:
                continue
                
            evaluated_index = int(evaluated_index)
            if evaluated_index < 1 or evaluated_index > len(group_members):
                continue
                
            evaluated_user = group_members[evaluated_index - 1].user_id
            
            evaluation = Evaluations.objects.create(
                assignment_id=assignment_obj,
                evaluator_id=evaluator,
                evaluatee_id=evaluated_user,
                points=request.POST.get(f'points_{i}'),
                comments=request.POST.get(f'comments_{i}')
            )
            
            if assignment_obj.enable_merits:
                merit_fields = [
                    'workcontribution',
                    'teaminteraction',
                    'teamawareness',
                    'qualityofwork',
                    'knowledgeandskills'
                ]
                
                merit_scores = {}
                for field in merit_fields:
                    score = request.POST.get(f'score_{field}_{i}')
                    if score:
                        merit_scores[f'score_{field}'] = int(score)
                
                if merit_scores:
                    MeritScores.objects.create(
                        evaluation_id=evaluation,
                        **merit_scores
                    )
                    
        messages.success(request, 'All evaluations submitted successfully!')
    except Exception as e:
        messages.error(request, f'Error submitting evaluations: {str(e)}')
        
    return redirect('evaluation', department=department, course=course, section_number=section_number, assignment=assignment)

@login_required
def section_dashboard(request, section_id):
    current_user = request.user
    section = Sections.objects.select_related(
        'course',
        'course__department',
        'term'
    ).prefetch_related(
        'enrollments',
        'enrollments__user_id',
        'assignments'
    ).get(id=section_id)
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=current_user).exists()
    is_coordinator = section.course.coordinator == current_user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have access to this section.')
        return redirect('index')
        
    students = Enrollments.objects.filter(
        section_id=section
    ).select_related('user_id').order_by('user_id__last_name')
    assignments = Assignments.objects.filter(
        section_id=section
    ).order_by('-due_date')
    
    now = timezone.now()
    def calculate_alert_level(assignment):
        time_until_due = (assignment.due_date - now).total_seconds()
        
        if time_until_due <= 3600:
            return 'red'
        elif time_until_due <= 86400:
            return 'yellow'
        elif assignment.available_date <= now and assignment.due_date >= now:
            return 'green'
        else:
            return 'gray'
            
    for assignment in assignments:
        assignment.evaluation_count = Evaluations.objects.filter(
            assignment_id=assignment
        ).count()
        available_date = timezone.make_aware(assignment.available_date) if timezone.is_naive(assignment.available_date) else assignment.available_date
        due_date = timezone.make_aware(assignment.due_date) if timezone.is_naive(assignment.due_date) else assignment.due_date
        is_assignment_active = available_date <= now and due_date >= now
        assignment.assignment_active = is_assignment_active
        assignment.alert_level = calculate_alert_level(assignment)
        
    total_evaluations = Evaluations.objects.filter(
        assignment_id__section_id=section
    ).count()
    
    active_assignments = sum(1 for a in assignments if hasattr(a, 'assignment_active') and a.assignment_active)
    upcoming_assignments = sum(1 for a in assignments if a.available_date > now)
    past_assignments = sum(1 for a in assignments if a.due_date < now)
    
    context = {
        'section': section,
        'students': students,
        'assignments': assignments,
        'user': current_user,
        'is_instructor': is_instructor,
        'is_coordinator': is_coordinator,
        'term': section.term,
        'evaluations': total_evaluations,
        'current_date': timezone.now().date(),
        'stats': {
            'term': {
                'value': section.term.name,
                'desc': f'{section.term.start_date} to {section.term.end_date}'
            },
            'instructor': {
                'value': f'{current_user.first_name} {current_user.last_name}',
                'desc': 'Primary instructor'
            },
            'students': {
                'value': students.count(),
                'desc': f'Enrolled in {section.course.department.id}{section.course.course_code}-{section.section_number}'
            },
            'assignments': {
                'value': assignments.count(),
                'desc': f'{active_assignments} active, {upcoming_assignments} upcoming, {past_assignments} past'
            },
            'evaluations': {
                'value': total_evaluations,
                'desc': f'Total peer evaluations submitted'
            }
        }
    }
    
    return render(request, 'instructor/section_dashboard.html', context)

@login_required
def view_assignment(request, assignment_id):
    current_user = request.user
    assignment = get_object_or_404(Assignments.objects.select_related(
        'section_id',
        'section_id__course',
        'section_id__course__department',
        'section_id__term'
    ), id=assignment_id)
    
    section = assignment.section_id
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=current_user).exists()
    is_coordinator = section.course.coordinator == current_user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to view this assignment.')
        return redirect('section_dashboard', section_id=section.id)

    if request.method == 'POST':
        assignment.delete()
        messages.success(request, 'Assignment deleted successfully.')
        return redirect('section_dashboard', section_id=section.id)
    
    enrolled_students = Enrollments.objects.filter(
        section_id=section
    ).select_related('user_id', 'group')
    
    total_students = enrolled_students.count()
    
    evaluations = Evaluations.objects.filter(
        assignment_id=assignment
    ).select_related('evaluator_id', 'evaluatee_id')
    
    submitted_count = len(set(evaluations.values_list('evaluator_id', flat=True)))
    submission_percentage = (submitted_count / total_students * 100) if total_students > 0 else 0
    
    class_avg_peer_score = evaluations.aggregate(avg=models.Avg('points'))['avg']
    
    students_data = []
    for student in enrolled_students:
        student_evals = evaluations.filter(evaluatee_id=student.user_id)
        has_submitted = evaluations.filter(evaluator_id=student.user_id).exists()
        student_score = student_evals.aggregate(avg=models.Avg('points'))['avg']
        
        all_evaluations = []
        for eval in student_evals:
            eval_data = {
                'id': eval.id,
                'evaluator': eval.evaluator_id,
                'points': eval.points,
                'comments': eval.comments,
                'is_self': eval.evaluator_id == eval.evaluatee_id,
                'submission_date': eval.submission_date
            }
            
            try:
                merit_scores = MeritScores.objects.filter(evaluation_id=eval)
                if merit_scores.exists():
                    merit = merit_scores.aggregate(
                        work_contribution=models.Avg('score_workcontribution'),
                        team_interaction=models.Avg('score_teaminteraction'),
                        team_awareness=models.Avg('score_teamawareness'),
                        quality_work=models.Avg('score_qualityofwork'),
                        knowledge_skills=models.Avg('score_knowledgeandskills')
                    )
                    eval_data['merit_scores'] = {
                        'work_contribution': merit['work_contribution'],
                        'team_interaction': merit['team_interaction'],
                        'team_awareness': merit['team_awareness'],
                        'quality_work': merit['quality_work'],
                        'knowledge_skills': merit['knowledge_skills']
                    }
            except Exception as e:
                print(f"Error processing merit scores for evaluation {eval.id}: {e}")
                eval_data['merit_scores'] = None
            
            all_evaluations.append(eval_data)
        
        merit_scores = []
        if assignment.enable_merits:
            merit_data = MeritScores.objects.filter(evaluation_id__in=student_evals)
            if merit_data.exists():
                work_score = merit_data.aggregate(avg=models.Avg('score_workcontribution'))['avg']
                team_score = merit_data.aggregate(avg=models.Avg('score_teaminteraction'))['avg']
                aware_score = merit_data.aggregate(avg=models.Avg('score_teamawareness'))['avg']
                quality_score = merit_data.aggregate(avg=models.Avg('score_qualityofwork'))['avg']
                skills_score = merit_data.aggregate(avg=models.Avg('score_knowledgeandskills'))['avg']
                
                merit_scores = [
                    {
                        'category': 'Work Contribution',
                        'score': round(work_score, 1) if work_score else 'N/A',
                        'color': 'primary'
                    },
                    {
                        'category': 'Team Interaction',
                        'score': round(team_score, 1) if team_score else 'N/A',
                        'color': 'primary'
                    },
                    {
                        'category': 'Team Awareness',
                        'score': round(aware_score, 1) if aware_score else 'N/A',
                        'color': 'primary'
                    },
                    {
                        'category': 'Quality of Work',
                        'score': round(quality_score, 1) if quality_score else 'N/A',
                        'color': 'primary'
                    },
                    {
                        'category': 'Knowledge & Skills',
                        'score': round(skills_score, 1) if skills_score else 'N/A',
                        'color': 'primary'
                    }
                ]
        
        flags = get_flags(student.user_id.id, assignment.id)
        
        students_data.append({
            'user_id': student.user_id,
            'student_score': student_score,
            'has_submitted': has_submitted,
            'flags': flags,
            'merit_scores': merit_scores,
            'evaluations': all_evaluations
        })
        
    context = {
        'assignment': assignment,
        'section': section,
        'students': students_data,
        'total_students': total_students,
        'submitted_count': submitted_count,
        'submission_percentage': submission_percentage,
        'current_date': timezone.now().date(),
        'class_avg_peer_score': class_avg_peer_score,
    }
    
    return render(request, 'instructor/view_assignment.html', context)

@login_required
def student_profile(request, username):
    current_user = request.user
    
    if not current_user.is_instructor:
        messages.error(request, 'You do not have permission to view student dashboards.')
        return redirect('index')
        
    try:
        student = Users.objects.get(username=username)
        if student.is_instructor:
            messages.error(request, 'Cannot view dashboard for an instructor.')
            return redirect('index')
            
        enrollments = Enrollments.objects.filter(
            user_id=student
        ).select_related(
            'section_id',
            'section_id__course',
            'section_id__course__department',
            'section_id__term',
            'group'
        ).order_by('-section_id__term__end_date')
        
        active_enrollments = enrollments.filter(
            section_id__term__end_date__gte=timezone.now().date()
        )
        past_enrollments = enrollments.filter(
            section_id__term__end_date__lt=timezone.now().date()
        )
        
        instructor_sections = Sections.objects.filter(
            sectioninstructors__user_id=current_user
        )
        
        assignments = Assignments.objects.filter(
            section_id__in=enrollments.values('section_id')
        ).select_related(
            'section_id',
            'section_id__course',
            'section_id__course__department',
            'section_id__term'
        ).order_by('-due_date')
        
        evaluations = Evaluations.objects.filter(
            evaluator_id=student,
            assignment_id__section_id__in=instructor_sections
        ).select_related(
            'assignment_id',
            'assignment_id__section_id',
            'assignment_id__section_id__course',
            'assignment_id__section_id__course__department',
            'assignment_id__section_id__term',
            'evaluatee_id'
        ).order_by('-submission_date')
        
        received_evaluations = Evaluations.objects.filter(
            evaluatee_id=student,
            assignment_id__section_id__in=instructor_sections
        ).select_related(
            'assignment_id',
            'assignment_id__section_id',
            'assignment_id__section_id__course',
            'assignment_id__section_id__course__department',
            'assignment_id__section_id__term',
            'evaluator_id'
        ).order_by('-submission_date')

        merit_scores_queryset = MeritScores.objects.filter(
            evaluation_id__in=received_evaluations
        )

        assignments_with_evaluations = []
        for assignment in assignments:
            assignment_evaluations = received_evaluations.filter(assignment_id=assignment)
            if assignment_evaluations.exists():
                processed_evaluations = []
                for evaluation in assignment_evaluations:
                    merit_data = MeritScores.objects.filter(evaluation_id=evaluation)
                    if merit_data.exists():
                        merit = merit_data.first()
                        merit_scores = [
                            {
                                'category': 'Work Contribution',
                                'score': round(merit.score_workcontribution, 1) if merit.score_workcontribution else 'N/A',
                                'color': 'primary'
                            },
                            {
                                'category': 'Team Interaction',
                                'score': round(merit.score_teaminteraction, 1) if merit.score_teaminteraction else 'N/A',
                                'color': 'primary'
                            },
                            {
                                'category': 'Team Awareness',
                                'score': round(merit.score_teamawareness, 1) if merit.score_teamawareness else 'N/A',
                                'color': 'primary'
                            },
                            {
                                'category': 'Quality of Work',
                                'score': round(merit.score_qualityofwork, 1) if merit.score_qualityofwork else 'N/A',
                                'color': 'primary'
                            },
                            {
                                'category': 'Knowledge & Skills',
                                'score': round(merit.score_knowledgeandskills, 1) if merit.score_knowledgeandskills else 'N/A',
                                'color': 'primary'
                            }
                        ]
                    else:
                        merit_scores = None
                    
                    processed_evaluations.append({
                        'evaluation': evaluation,
                        'merit_scores': merit_scores
                    })

                flags = get_flags(student.id, assignment.id)
                
                assignments_with_evaluations.append({
                    'assignment': assignment,
                    'evaluations': processed_evaluations,
                    'flags': flags
                })

        assignments_with_given_evaluations = []
        for assignment in assignments:
            assignment_evaluations = evaluations.filter(assignment_id=assignment)
            if assignment_evaluations.exists():
                processed_evaluations = []
                for evaluation in assignment_evaluations:
                    merit_data = MeritScores.objects.filter(evaluation_id=evaluation)
                    if merit_data.exists():
                        merit = merit_data.first()
                        merit_scores = [
                            {
                                'category': 'Work Contribution',
                                'score': round(merit.score_workcontribution, 1) if merit.score_workcontribution else 'N/A',
                                'color': 'primary'
                            },
                            {
                                'category': 'Team Interaction',
                                'score': round(merit.score_teaminteraction, 1) if merit.score_teaminteraction else 'N/A',
                                'color': 'primary'
                            },
                            {
                                'category': 'Team Awareness',
                                'score': round(merit.score_teamawareness, 1) if merit.score_teamawareness else 'N/A',
                                'color': 'primary'
                            },
                            {
                                'category': 'Quality of Work',
                                'score': round(merit.score_qualityofwork, 1) if merit.score_qualityofwork else 'N/A',
                                'color': 'primary'
                            },
                            {
                                'category': 'Knowledge & Skills',
                                'score': round(merit.score_knowledgeandskills, 1) if merit.score_knowledgeandskills else 'N/A',
                                'color': 'primary'
                            }
                        ]
                    else:
                        merit_scores = None
                    
                    processed_evaluations.append({
                        'evaluation': evaluation,
                        'merit_scores': merit_scores
                    })

                flags = get_flags(student.id, assignment.id)
                
                assignments_with_given_evaluations.append({
                    'assignment': assignment,
                    'evaluations': processed_evaluations,
                    'flags': flags
                })

        work_contribution_avg = merit_scores_queryset.aggregate(avg=models.Avg('score_workcontribution'))['avg'] or 0
        team_interaction_avg = merit_scores_queryset.aggregate(avg=models.Avg('score_teaminteraction'))['avg'] or 0
        team_awareness_avg = merit_scores_queryset.aggregate(avg=models.Avg('score_teamawareness'))['avg'] or 0
        quality_of_work_avg = merit_scores_queryset.aggregate(avg=models.Avg('score_qualityofwork'))['avg'] or 0
        knowledge_and_skills_avg = merit_scores_queryset.aggregate(avg=models.Avg('score_knowledgeandskills'))['avg'] or 0

        enrolled_since = Enrollments.objects.filter(user_id=student).select_related('section_id__term').order_by('enrollment_date').first()

        context = {
            'student': student,
            'active_enrollments': active_enrollments,
            'past_enrollments': past_enrollments,
            'assignments': assignments_with_evaluations,
            'given_assignments': assignments_with_given_evaluations,
            'now': timezone.now(),
            'work_contribution_avg': round(work_contribution_avg, 1),
            'team_interaction_avg': round(team_interaction_avg, 1),
            'team_awareness_avg': round(team_awareness_avg, 1),
            'quality_of_work_avg': round(quality_of_work_avg, 1),
            'knowledge_and_skills_avg': round(knowledge_and_skills_avg, 1),
            'enrolled_since': enrolled_since,
        }
        
        return render(request, 'instructor/student_profile.html', context)
        
    except Users.DoesNotExist:
        messages.error(request, 'Student not found.')
        return redirect('index')

@login_required
def add_course(request):
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            try:
                course = form.save()
                if hasattr(form, 'coordinator_assigned'):
                    coordinator_name = "You" if form.existing_course.coordinator == request.user else f"{form.existing_course.coordinator.first_name} {form.existing_course.coordinator.last_name}"
                    messages.success(request, f'Course {form.existing_course.department.id}{form.existing_course.course_code} already exists. {coordinator_name} have been assigned as the coordinator.')
                    if form.existing_course.name != form.cleaned_data['name']:
                        messages.info(request, f'Course name has been updated to: {form.existing_course.name}')
                else:
                    messages.success(request, f'Course {course.department.id}{course.course_code} - {course.name} added successfully.')
                return redirect('index')
            except Exception as e:
                messages.error(request, f'Error adding course: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        messages.error(request, f"{field.title()}: {error}")
        return redirect('index')
    return redirect('index')

@login_required
def add_instructor(request):
    if request.method == 'POST':
        form = InstructorForm(request.POST)
        if form.is_valid():
            try:
                instructor = form.save()
                messages.success(request, f'Instructor {instructor.first_name} {instructor.last_name} added successfully!')
            except Exception as e:
                if 'username' in str(e).lower():
                    messages.error(request, 'An instructor with this username already exists.')
                else:
                    messages.error(request, f'Error adding instructor: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__' and 'username' in error.lower():
                        continue
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        messages.error(request, f"{field.title()}: {error}")
    return redirect('index')

@login_required
def add_section(request):
    current_user = request.user
    
    is_coordinator = Courses.objects.filter(coordinator=current_user).exists()
    if not is_coordinator:
        messages.error(request, 'Only course coordinators can add sections.')
        return redirect('index')
        
    if request.method == 'POST':
        form = SectionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.info(request, f'Section {form.cleaned_data["term"]} {form.cleaned_data["course"].department.id}{form.cleaned_data["course"].course_code}-{form.cleaned_data["section_number"]} added successfully!')
            return redirect('index')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, f'Section {form.cleaned_data["section_number"]} in {form.cleaned_data["course"].department.id}{form.cleaned_data["course"].course_code} already exists for {form.cleaned_data["term"]}.')
                    else:
                        messages.error(request, f"{field.title()}: {error}")
    return redirect('index')

@login_required
def add_assignment(request):
    current_user = request.user
    
    is_instructor = SectionInstructors.objects.filter(user_id=current_user).exists()
    is_coordinator = Courses.objects.filter(coordinator=current_user).exists()
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to add assignments.')
        return redirect('index')
        
    if request.method == 'POST':
        form = AssignmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.info(request, 'Assignment added successfully!')
            return redirect('index')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.title()}: {error}")
    else:
        form = AssignmentForm()
        
    if is_instructor:
        sections = Sections.objects.filter(
            sectioninstructors__user_id=current_user,
            term__end_date__gte=timezone.now().date()
        ).select_related('course', 'term')
    else:
        sections = Sections.objects.filter(
            course__coordinator=current_user,
            term__end_date__gte=timezone.now().date()
        ).select_related('course', 'term')
    
    form.fields['section_id'].queryset = sections
    
    context = {
        'form': form,
        'sections': sections
    }
    return render(request, 'instructor/add_forms/assignment.html', context)

@login_required
def add_students(request):
    current_user = request.user
    
    is_instructor = SectionInstructors.objects.filter(user_id=current_user).exists()
    is_coordinator = Courses.objects.filter(coordinator=current_user).exists()
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to add students.')
        return redirect('index')
        
    if request.method == 'POST':
        section_id = request.POST.get('section')
        student_ids = request.POST.getlist('students')
        
        if not section_id or not student_ids:
            messages.error(request, 'Please select a section and at least one student.')
            return redirect('add_students')
            
        try:
            section = Sections.objects.get(id=section_id)
            
            if not (section.sectioninstructors_set.filter(user_id=current_user).exists() or 
                   section.course.coordinator == current_user):
                messages.error(request, 'You do not have permission to add students to this section.')
                return redirect('add_students')
                
            for student_id in student_ids:
                try:
                    student = Users.objects.get(id=student_id)
                    if not student.is_instructor: 
                        Enrollments.objects.create(
                            user_id=student,
                            section_id=section,
                            added_by=current_user
                        )
                except Users.DoesNotExist:
                    continue
                    
            messages.info(request, 'Students added successfully!')
            return redirect('section_dashboard', section_id=section_id)
            
        except Sections.DoesNotExist:
            messages.error(request, 'Selected section not found.')
            return redirect('add_students')
            
    if is_instructor:
        sections = Sections.objects.filter(
            sectioninstructors__user_id=current_user,
            term__end_date__gte=timezone.now().date()
        ).select_related('course', 'term')
    else:
        sections = Sections.objects.filter(
            course__coordinator=current_user,
            term__end_date__gte=timezone.now().date()
        ).select_related('course', 'term')
        
    potential_students = Users.objects.filter(
        is_instructor=False
    ).order_by('last_name', 'first_name')
    
    context = {
        'sections': sections,
        'students': potential_students
    }
    return render(request, 'instructor/add_forms/students.html', context)

@login_required
def add_student(request):
    if request.method == 'POST':
        form = StudentForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Student added successfully.')
                return redirect('index')
            except Exception as e:
                messages.error(request, f'Error adding student: {str(e)}')
    else:
        form = StudentForm()
    
    return render(request, 'instructor/add_forms/student.html', {'form': form})

@login_required
def section_add_student(request, section_id):
    current_user = request.user
    section = get_object_or_404(Sections.objects.select_related('course', 'course__department', 'term'), id=section_id)
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=current_user).exists()
    is_coordinator = section.course.coordinator == current_user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to add students to this section.')
        return redirect('section_dashboard', section_id=section_id)
    
    if request.method == 'POST':
        form = SectionAddStudentForm(request.POST, section=section)
        if form.is_valid():
            enrollments = form.save(instructor_user=current_user)
            messages.info(request, f'{len(enrollments)} student(s) added successfully to the section!')
            return redirect('section_dashboard', section_id=section_id)
        else:

            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.title()}: {error}")
    else:
        form = SectionAddStudentForm(section=section)
    
    context = {
        'form': form,
        'section': section
    }
    
    return render(request, 'instructor/add_forms/section_student.html', context)

@login_required
def section_add_assignment(request, section_id):
    current_user = request.user
    section = get_object_or_404(Sections.objects.select_related('course', 'course__department', 'term'), id=section_id)
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=current_user).exists()
    is_coordinator = section.course.coordinator == current_user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to add assignments to this section.')
        return redirect('section_dashboard', section_id=section_id)
    
    if request.method == 'POST':
        form = SectionAddAssignmentForm(request.POST, section=section)
        if form.is_valid():
            assignment = form.save()
            messages.info(request, f'Assignment "{assignment.name}" added successfully!')
            return redirect('section_dashboard', section_id=section_id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.title()}: {error}")
    else:
        form = SectionAddAssignmentForm(section=section)
    
    context = {
        'form': form,
        'section': section
    }
    
    return render(request, 'instructor/add_forms/section_assignment.html', context)

@login_required
def section_manage_groups(request, section_id):
    current_user = request.user
    section = get_object_or_404(Sections.objects.select_related('course', 'course__department', 'term'), id=section_id)
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=current_user).exists()
    is_coordinator = section.course.coordinator == current_user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to manage groups for this section.')
        return redirect('section_dashboard', section_id=section_id)
    
    students = Enrollments.objects.filter(section_id=section).select_related('user_id', 'group')
    groups = Groups.objects.filter(section_id=section)
    
    if not groups.exists():
        default_group = Groups.objects.create(
            name="1",
            section_id=section
        )
        groups = Groups.objects.filter(section_id=section)
    
    unassigned_students = students.filter(group__isnull=True)
    
    group_list = []
    for group in groups:
        group_students = list(group.enrollments_set.all().select_related('user_id'))
                
        group_list.append({
            'group': group,
            'students': group_students,
            'count': len(group_students)
        })
    
    total_students = students.count()
    total_groups = groups.count()
    avg_group_size = round(total_students / total_groups, 1) if total_groups > 0 else 0
    
    unassigned_count = unassigned_students.count()
    if unassigned_count > 0:
        messages.warning(request, f'There are {unassigned_count} unassigned student{"s" if unassigned_count != 1 else ""} that need to be placed in groups.')
    
    if request.method == 'POST':
        if 'add_group' in request.POST:
            highest_group = groups.order_by('-name').first()
            try:
                next_number = int(highest_group.name) + 1 if highest_group else 1
            except ValueError:
                next_number = groups.count() + 1
            
            new_group = Groups.objects.create(
                name=str(next_number),
                section_id=section
            )
            messages.success(request, f'Created new group {new_group.name}')
            return redirect('section_manage_groups', section_id=section_id)
        elif 'form_groups' in request.POST:
            form = GroupFormationMethodForm(request.POST)
            if form.is_valid():
                try:
                    method = form.cleaned_data['method']
                    group_size = form.cleaned_data['group_size']
                    
                    if total_students < group_size:
                        messages.error(request, f'Group size ({group_size}) cannot be larger than total number of students ({total_students})')
                        context = {
                            'section': section,
                            'students': students,
                            'groups': groups,
                            'unassigned_students': unassigned_students,
                            'group_list': group_list,
                            'form': form,
                            'avg_group_size': avg_group_size,
                        }
                        return render(request, 'instructor/add_forms/section_groups.html', context)
                    
                    all_students = list(students)
                    
                    Groups.objects.filter(section_id=section).delete()
                    
                    if method == 'random':
                        import random
                        random.shuffle(all_students)
                    else:
                        student_scores = []
                        for student in all_students:
                            merit_scores = MeritScores.objects.filter(
                                evaluation_id__evaluatee_id=student.user_id,
                                evaluation_id__assignment_id__section_id=section
                            )
                            
                            if merit_scores.exists():
                                avg_scores = {
                                    'workcontribution': merit_scores.aggregate(avg=models.Avg('score_workcontribution'))['avg'],
                                    'teaminteraction': merit_scores.aggregate(avg=models.Avg('score_teaminteraction'))['avg'],
                                    'teamawareness': merit_scores.aggregate(avg=models.Avg('score_teamawareness'))['avg'],
                                    'qualityofwork': merit_scores.aggregate(avg=models.Avg('score_qualityofwork'))['avg'],
                                    'knowledgeandskills': merit_scores.aggregate(avg=models.Avg('score_knowledgeandskills'))['avg']
                                }
                                
                                overall_avg = sum(avg_scores.values()) / len(avg_scores)
                            else:
                                overall_avg = 3.0 
                            
                            student_scores.append((student, overall_avg))
                        
                        student_scores.sort(key=lambda x: x[1], reverse=True)
                        all_students = [student for student, _ in student_scores]
                    
                    Enrollments.objects.filter(section_id=section).update(group=None)
                    
                    current_group = 1
                    groups = []
                    
                    for i in range(0, len(all_students), group_size):
                        group = Groups.objects.create(
                            name=str(current_group),
                            section_id=section
                        )
                        groups.append(group)
                        
                        for student in all_students[i:i + group_size]:
                            student.group = group
                            student.save()
                        
                        current_group += 1
                    
                    leftover_students = []
                    for group in groups:
                        group_students = list(Enrollments.objects.filter(group=group))
                        if len(group_students) < group_size - 1:
                            leftover_students.extend(group_students)
                            group.delete()
                    
                    if leftover_students:
                        non_empty_groups = Groups.objects.filter(section_id=section).annotate(
                            student_count=models.Count('enrollments')
                        ).filter(student_count__gt=0)
                        
                        if non_empty_groups.exists():
                            for student in leftover_students:
                                if method == 'random':
                                    import random
                                    target_group = random.choice(list(non_empty_groups))
                                else:
                                    student_score = MeritScores.objects.filter(
                                        evaluation_id__evaluatee_id=student.user_id,
                                        evaluation_id__assignment_id__section_id=section
                                    ).aggregate(
                                        avg=models.Avg(
                                            (models.F('score_workcontribution') +
                                             models.F('score_teaminteraction') +
                                             models.F('score_teamawareness') +
                                             models.F('score_qualityofwork') +
                                             models.F('score_knowledgeandskills')) / 5
                                        )
                                    )['avg'] or 3.0
                                    
                                    min_diff = float('inf')
                                    target_group = None
                                    for group in non_empty_groups:
                                        current_size = Enrollments.objects.filter(group=group).count()
                                        if current_size >= group_size:
                                            continue
                                            
                                        group_avg = MeritScores.objects.filter(
                                            evaluation_id__evaluatee_id__in=Enrollments.objects.filter(
                                                group=group
                                            ).values_list('user_id', flat=True),
                                            evaluation_id__assignment_id__section_id=section
                                        ).aggregate(
                                            avg=models.Avg(
                                                (models.F('score_workcontribution') +
                                                 models.F('score_teaminteraction') +
                                                 models.F('score_teamawareness') +
                                                 models.F('score_qualityofwork') +
                                                 models.F('score_knowledgeandskills')) / 5
                                            )
                                        )['avg'] or 3.0
                                        
                                        diff = abs(student_score - group_avg)
                                        if diff < min_diff:
                                            min_diff = diff
                                            target_group = group
                                
                                if not target_group:
                                    target_group = non_empty_groups.order_by('student_count').first()
                                
                                student.group = target_group
                                student.save()
                    
                    messages.success(request, f'Students have been assigned to groups using {method} distribution')
                    return redirect('section_manage_groups', section_id=section_id)
                except Exception as e:
                    messages.error(request, f'Error forming groups: {str(e)}')
            else:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f"{field.title()}: {error}")
        
        elif 'save_groups' in request.POST:
            try:
                changes_made = 0
                
                for key, value in request.POST.items():
                    if key.startswith('student_'):
                        student_id = key.replace('student_', '')
                        group_id = value
                        
                        try:
                            user = Users.objects.get(id=student_id)
                            enrollment = Enrollments.objects.get(user_id=user, section_id=section)
                            
                            if group_id == 'unassigned':
                                if enrollment.group is not None:
                                    enrollment.group = None
                                    enrollment.save()
                                    changes_made += 1
                            else:
                                try:
                                    if group_id.startswith('new-group-'):
                                        group_name = group_id.replace('new-group-', '')
                                        new_group = Groups.objects.create(
                                            name=group_name,
                                            section_id=section
                                        )
                                        enrollment.group = new_group
                                        enrollment.save()
                                        changes_made += 1
                                    else:
                                        group = Groups.objects.get(id=group_id, section_id=section)
                                        if enrollment.group != group:
                                            enrollment.group = group
                                            enrollment.save()
                                            changes_made += 1
                                except Groups.DoesNotExist:
                                    messages.warning(request, f'Could not find group with ID {group_id}')
                                    continue
                        except Users.DoesNotExist:
                            messages.warning(request, f'Could not find user with ID {student_id}')
                            continue
                        except Enrollments.DoesNotExist:
                            messages.warning(request, f'Could not find enrollment for student ID {student_id} in section {section_id}')
                            continue
                
                empty_groups = Groups.objects.filter(
                    section_id=section
                ).annotate(
                    student_count=models.Count('enrollments')
                ).filter(student_count=0)
                
                if empty_groups.exists():
                    empty_groups.delete()
                    messages.info(request, f'Removed {empty_groups.count()} empty groups')
                
                if changes_made > 0:
                    messages.success(request, f'Group assignments saved successfully! ({changes_made} changes made)')
                else:
                    messages.info(request, 'No changes were made to group assignments.')
                return redirect('section_dashboard', section_id=section_id)
            except Exception as e:
                messages.error(request, f'Error saving group assignments: {str(e)}')
    else:
        form = GroupFormationMethodForm()
    
    context = {
        'section': section,
        'students': students,
        'groups': groups,
        'unassigned_students': unassigned_students,
        'group_list': group_list,
        'form': form,
        'avg_group_size': avg_group_size,
    }
    
    return render(request, 'instructor/add_forms/section_groups.html', context)

@login_required
def add_term(request):
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to add terms.')
        return redirect('index')
        
    if request.method == 'POST':
        form = TermForm(request.POST)
        if form.is_valid():
            term = form.save()
            messages.success(request, f'Term {term.name} has been added successfully.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == 'name':
                        messages.error(request, 'A term with this name already exists.')
                    elif field == '__all__':
                        messages.error(request, error)
                    else:
                        messages.error(request, f"{field.title()}: {error}")
    return redirect('index')

@login_required
def add_department(request):
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to add departments.')
        return redirect('index')
    
    instructors = Users.objects.filter(is_instructor=True).order_by('last_name', 'first_name')
    
    if request.method == 'POST':
        dept_id = request.POST.get('id')
        name = request.POST.get('name')
        department_head_id = request.POST.get('department_head')
        
        if not dept_id or not name:
            messages.error(request, 'Department ID and name are required.')
            return render(request, 'instructor/add_forms/department.html', {'instructors': instructors})
            
        if department_head_id:
            try:
                department_head = Users.objects.get(id=department_head_id)
            except Users.DoesNotExist:
                messages.error(request, 'Selected department head does not exist.')
                return render(request, 'instructor/add_forms/department.html', {'instructors': instructors})
        else:
            department_head = None
            
        try:
            try:
                existing_dept = Departments.objects.get(id=dept_id.upper())
                if existing_dept.department_head is None:
                    existing_dept.department_head = department_head
                    if existing_dept.name != name:
                        existing_dept.name = name
                        existing_dept.save()
                        messages.success(request, f'Department {existing_dept.id} already exists. You have been assigned as the department head.')
                        messages.info(request, f'Department name has been updated to: {existing_dept.name}')
                    else:
                        existing_dept.save()
                        messages.success(request, f'Department {existing_dept.id} already exists. You have been assigned as the department head.')
                else:
                    messages.error(request, f'Department {existing_dept.id} already exists in the system. {existing_dept.department_head.first_name} {existing_dept.department_head.last_name} is the current department head.')
                return redirect('index')
            except Departments.DoesNotExist:
                department = Departments.objects.create(
                    id=dept_id.upper(),
                    name=name,
                    department_head=department_head
                )
                messages.success(request, f'Department {department.name} ({department.id}) has been added successfully.')
                return redirect('index')
        except Exception as e:
            messages.error(request, f'Error adding department: {str(e)}')
            return render(request, 'instructor/add_forms/department.html', {'instructors': instructors})
    
    return render(request, 'instructor/add_forms/department.html', {'instructors': instructors})

class CustomLogoutView(LogoutView):
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        messages.success(request, 'You have been successfully logged out.')
        return redirect('login')

@login_required
def export_grades(request, section_id):
    current_user = request.user
    section = get_object_or_404(Sections.objects.select_related(
        'course',
        'course__department',
        'term'
    ), id=section_id)
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=current_user).exists()
    is_coordinator = section.course.coordinator == current_user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to export grades for this section.')
        return redirect('section_dashboard', section_id=section_id)

    assignments = Assignments.objects.filter(section_id=section).order_by('due_date')
    students = Enrollments.objects.filter(section_id=section).select_related('user_id', 'group')
    timestamp = datetime.now().strftime('%Y-%m-%d-%H-%M')
    filename = f"{section.term.name} {section.course.department.id}{section.course.course_code}-{section.section_number} LAB_GradesExport_{timestamp}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    
    if settings.BRIGHTSPACE_ENABLED:
        header = ['OrgDefinedId', 'Username', 'Last Name', 'First Name', 'Group']
        for assignment in assignments:
            header.append(f'{assignment.name} Peer Eval Points Grade <Numeric MaxPoints:{assignment.max_points_self}>')
        header.append('End-of-Line Indicator')
        writer.writerow(header)
    else:
        header = ['ID', 'Username', 'Last Name', 'First Name', 'Group']
        for assignment in assignments:
            header.append(f'{assignment.name} (/{assignment.max_points_self})')
        writer.writerow(header)

    for student in students:
        row = []
        if settings.BRIGHTSPACE_ENABLED:
            row.extend([
                f'#{student.user_id.id}',
                f'#{student.user_id.username}',
                student.user_id.last_name,
                student.user_id.first_name,
                f'Group {student.group.name}' if student.group else ''
            ])
        else:
            row.extend([
                student.user_id.id,
                student.user_id.username,
                student.user_id.last_name,
                student.user_id.first_name,
                f'Group {student.group.name}' if student.group else ''
            ])

        for assignment in assignments:
            evaluations = Evaluations.objects.filter(
                assignment_id=assignment,
                evaluatee_id=student.user_id
            )
            
            if evaluations.exists():
                total_points = evaluations.aggregate(
                    total_points=models.Sum('points')
                )['total_points']
                
                num_evaluators = evaluations.count()
                if num_evaluators > 0:
                    avg_points = total_points / num_evaluators
                    row.append(round(avg_points, 2) if avg_points is not None else '')
                else:
                    row.append('')
            else:
                row.append('')

        if settings.BRIGHTSPACE_ENABLED:
            row.append('#')
            
        writer.writerow(row)
        
    return response

@login_required
def evaluation_view(request, eval_id):
    evaluation = get_object_or_404(Evaluations, id=eval_id)
    
    is_instructor = SectionInstructors.objects.filter(
        section_id=evaluation.assignment_id.section_id,
        user_id=request.user
    ).exists()
    
    is_evaluator = evaluation.evaluator_id == request.user
    
    if not (is_instructor or is_evaluator):
        raise PermissionDenied("You do not have permission to view this evaluation.")
    
    try:
        merit_scores = MeritScores.objects.get(evaluation_id=evaluation)
    except MeritScores.DoesNotExist:
        merit_scores = None
    
    other_evaluations_total = evaluation.assignment_id.get_evaluations_total_for_user(
        evaluation.evaluator_id.id,
        exclude_evaluation_id=evaluation.id
    )
    
    group_size = evaluation.assignment_id.get_group_size_for_user(evaluation.evaluator_id.id)
    
    max_points_for_group = evaluation.assignment_id.get_max_points_for_group(group_size)
    
    remaining_points = max_points_for_group - other_evaluations_total - evaluation.points
    
    now = timezone.now()
    evaluation.assignment_id.assignment_active = (
        evaluation.assignment_id.available_date <= now and 
        evaluation.assignment_id.due_date >= now
    )
    
    context = {
        'evaluation': evaluation,
        'merit_scores': merit_scores,
        'is_instructor': is_instructor,
        'is_evaluator': is_evaluator,
        'other_evaluations_total': other_evaluations_total,
        'group_size': group_size,
        'max_points_for_group': max_points_for_group,
        'remaining_points': remaining_points
    }
    
    return render(request, 'instructor/evaluation_view.html', context)

@login_required
def import_wizard(request, section_id):
    current_user = request.user
    section = get_object_or_404(Sections.objects.select_related(
        'course',
        'course__department',
        'term'
    ), id=section_id)
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=current_user).exists()
    is_coordinator = section.course.coordinator == current_user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to import data for this section.')
        return redirect('section_dashboard', section_id=section_id)

    def extract_group_number(group_text):
        if not group_text:
            return None
        numbers = re.findall(r'\d+', group_text)
        return numbers[0] if numbers else None

    if request.method == 'POST' and request.FILES.get('import_file'):
        try:
            csv_file = request.FILES['import_file']
            if not csv_file.name.endswith('.csv'):
                messages.error(request, 'Please upload a CSV file.')
                return redirect('import_wizard', section_id=section_id)

            decoded_file = csv_file.read().decode('utf-8').splitlines()
            csv_reader = csv.DictReader(decoded_file)
            
            is_brightspace = 'OrgDefinedId' in csv_reader.fieldnames and 'End-of-Line Indicator' in csv_reader.fieldnames
            
            if is_brightspace:
                required_fields = ['OrgDefinedId', 'Username', 'Last Name', 'First Name']
            else:
                required_fields = ['ID', 'Username', 'First Name', 'Last Name']
                
            if not all(field in csv_reader.fieldnames for field in required_fields):
                messages.error(request, f'CSV file must contain the following columns: {", ".join(required_fields)}')
                return redirect('import_wizard', section_id=section_id)

            group_column = None
            for col in csv_reader.fieldnames:
                if 'group' in col.lower():
                    group_column = col
                    break

            users_created = 0
            users_updated = 0
            enrollments_created = 0
            errors = []
            
            rows_to_process = []
            existing_usernames = set(Users.objects.values_list('username', flat=True))
            username_id_map = {}
            
            for row in csv_reader:
                try:
                    if is_brightspace:
                        user_id = row['OrgDefinedId'].strip('#')
                        username = row['Username'].strip('#')
                        group_name = extract_group_number(row.get(group_column, '')) if group_column else None
                    else:
                        user_id = row['ID'].strip()
                        username = row['Username'].strip()
                        group_name = extract_group_number(row.get(group_column, '')) if group_column else None
                        
                    first_name = row['First Name'].strip()
                    last_name = row['Last Name'].strip()

                    if not all([user_id, username, first_name, last_name]):
                        errors.append(f'Row {csv_reader.line_num}: All fields are required')
                        continue

                    if username in username_id_map:
                        if username_id_map[username] != user_id:
                            errors.append(f'Row {csv_reader.line_num}: Username "{username}" is used by multiple students')
                            continue
                    else:
                        username_id_map[username] = user_id

                    try:
                        existing_user = Users.objects.get(username=username)
                        if existing_user.id != user_id:
                            rows_to_process.append({
                                'user_id': existing_user.id,
                                'username': existing_user.username,
                                'first_name': existing_user.first_name,
                                'last_name': existing_user.last_name,
                                'group_name': group_name,
                                'line_num': csv_reader.line_num,
                                'is_existing': True
                            })
                            continue
                    except Users.DoesNotExist:
                        pass

                    rows_to_process.append({
                        'user_id': user_id,
                        'username': username,
                        'first_name': first_name,
                        'last_name': last_name,
                        'group_name': group_name,
                        'line_num': csv_reader.line_num,
                        'is_existing': False
                    })

                except Exception as e:
                    errors.append(f'Row {csv_reader.line_num}: {str(e)}')

            if not errors:
                for row_data in rows_to_process:
                    try:
                        if row_data['is_existing']:
                            user = Users.objects.get(username=row_data['username'])
                        else:
                            user = Users.objects.filter(id=row_data['user_id']).first()
                            if user:
                                if (user.username != row_data['username'] or 
                                    user.first_name != row_data['first_name'] or 
                                    user.last_name != row_data['last_name']):
                                    user.username = row_data['username']
                                    user.first_name = row_data['first_name']
                                    user.last_name = row_data['last_name']
                                    user.save()
                                    users_updated += 1
                            else:
                                user = Users.objects.create(
                                    id=row_data['user_id'],
                                    username=row_data['username'],
                                    first_name=row_data['first_name'],
                                    last_name=row_data['last_name'],
                                    is_instructor=False
                                )
                                password = str(row_data['user_id'])
                                user.set_password(password)
                                user.save()
                                users_created += 1

                        enrollment, created = Enrollments.objects.get_or_create(
                            user_id=user,
                            section_id=section,
                            defaults={'added_by': current_user}
                        )
                        if created:
                            enrollments_created += 1

                        if row_data['group_name']:
                            group, _ = Groups.objects.get_or_create(
                                name=row_data['group_name'],
                                section_id=section
                            )
                            enrollment.group = group
                            enrollment.save()

                    except Exception as e:
                        errors.append(f'Row {row_data["line_num"]}: {str(e)}')

            if errors:
                messages.error(request, 'Import failed. Please fix the following errors and try again:')
                for error in errors:
                    messages.error(request, error)
            else:
                status_parts = []
                if users_created > 0:
                    status_parts.append(f'{users_created} new users created')
                if users_updated > 0:
                    status_parts.append(f'{users_updated} existing users updated')
                if enrollments_created > 0:
                    status_parts.append(f'{enrollments_created} new enrollments created')
                
                if status_parts:
                    messages.success(request, f'Import completed successfully: {", ".join(status_parts)}.')

            return redirect('section_dashboard', section_id=section_id)

        except Exception as e:
            messages.error(request, f'Error processing CSV file: {str(e)}')
            return redirect('import_wizard', section_id=section_id)

    context = {
        'section': section
    }
    return render(request, 'instructor/import_wizard.html', context)

@login_required
def import_confirm(request, section_id):
    if request.method != 'POST':
        return redirect('section_dashboard', section_id=section_id)
        
    current_user = request.user
    section = get_object_or_404(Sections.objects.select_related(
        'course',
        'course__department',
        'term'
    ), id=section_id)
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=current_user).exists()
    is_coordinator = section.course.coordinator == current_user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to import data for this section.')
        return redirect('section_dashboard', section_id=section_id)

    try:
        assignments = []
        for key, value in request.POST.items():
            if key.startswith('assignment_'):
                assignment_id = key.replace('assignment_', '')
                name = request.POST.get(f'name_{assignment_id}')
                max_points = request.POST.get(f'max_points_{assignment_id}')
                available_date = request.POST.get(f'available_date_{assignment_id}')
                due_date = request.POST.get(f'due_date_{assignment_id}')
                available_time = request.POST.get(f'available_time_{assignment_id}')
                due_time = request.POST.get(f'due_time_{assignment_id}')
                
                assignment, created = Assignments.objects.get_or_create(
                    name=name,
                    section_id=section,
                    defaults={
                        'max_points_self': max_points,
                        'available_date': available_date,
                        'due_date': due_date,
                        'available_time': available_time,
                        'due_time': due_time,
                        'self_eval': True,
                        'enable_merits': False
                    }
                )
                assignments.append(assignment)

        for key, value in request.POST.items():
            if key.startswith('user_'):
                user_id = key.replace('user_', '')
                username = request.POST.get(f'username_{user_id}')
                first_name = request.POST.get(f'first_name_{user_id}')
                last_name = request.POST.get(f'last_name_{user_id}')
                group_name = request.POST.get(f'group_{user_id}')
                
                try:
                    student = Users.objects.get(id=user_id)
                    if (student.first_name != first_name or 
                        student.last_name != last_name or 
                        student.username != username):
                        student.first_name = first_name
                        student.last_name = last_name
                        student.username = username
                        student.save()
                except Users.DoesNotExist:
                    student = Users.objects.create(
                        id=user_id,
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        is_instructor=False
                    )
                    student.set_password(user_id)
                    student.save()
                
                enrollment, created = Enrollments.objects.get_or_create(
                    user_id=student,
                    section_id=section,
                    defaults={'added_by': current_user}
                )
                
                if group_name:
                    group, _ = Groups.objects.get_or_create(
                        name=group_name,
                        section_id=section
                    )
                    enrollment.group = group
                    enrollment.save()
                
                for assignment in assignments:
                    grade = request.POST.get(f'grade_{user_id}_{assignment.id}')
                    if grade:
                        try:
                            points = float(grade)
                            evaluation, created = Evaluations.objects.get_or_create(
                                assignment_id=assignment,
                                evaluatee_id=student,
                                defaults={'points': points}
                            )
                            if not created:
                                evaluation.points = points
                                evaluation.save()
                        except ValueError:
                            continue

        messages.success(request, 'Data imported successfully!')
    except Exception as e:
        messages.error(request, f'Error importing data: {str(e)}')
    
    return redirect('section_dashboard', section_id=section_id)

@login_required
def section_student(request, section_id):
    section = get_object_or_404(Sections.objects.select_related(
        'course',
        'course__department',
        'term'
    ), id=section_id)
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=request.user).exists()
    is_coordinator = section.course.coordinator == request.user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to manage students in this section.')
        return redirect('section_dashboard', section_id=section_id)
    
    enrolled_students_list = Enrollments.objects.filter(
        section_id=section
    ).select_related('user_id', 'group').order_by('user_id__last_name', 'user_id__first_name')
    
    available_students = Users.objects.filter(
        is_instructor=False
    ).exclude(
        id__in=enrolled_students_list.values_list('user_id', flat=True)
    ).order_by('last_name', 'first_name')
    
    enrolled_per_page = int(request.GET.get('enrolled_per_page', 16))
    per_page = int(request.GET.get('per_page', 16))
    
    enrolled_paginator = Paginator(enrolled_students_list, enrolled_per_page)
    try:
        enrolled_page = int(request.GET.get('enrolled_page', 1))
        enrolled_students = enrolled_paginator.page(enrolled_page)
    except (PageNotAnInteger, ValueError):
        enrolled_students = enrolled_paginator.page(1)
    except EmptyPage:
        enrolled_students = enrolled_paginator.page(enrolled_paginator.num_pages)
    
    available_paginator = Paginator(available_students, per_page)
    try:
        page = int(request.GET.get('page', 1))
        paginated_students = available_paginator.page(page)
    except (PageNotAnInteger, ValueError):
        paginated_students = available_paginator.page(1)
    except EmptyPage:
        paginated_students = available_paginator.page(available_paginator.num_pages)
    
    if request.method == 'POST':
        if 'students' in request.POST:
            selected_students = request.POST.getlist('students')
            if selected_students:
                for student_id in selected_students:
                    student = get_object_or_404(Users, id=student_id)
                    Enrollments.objects.get_or_create(
                        user_id=student,
                        section_id=section,
                        defaults={'added_by': request.user}
                    )
                messages.success(request, f'Successfully added {len(selected_students)} student(s) to the section.')
                return redirect('section_student', section_id=section_id)
    
    context = {
        'section': section,
        'enrolled_students': enrolled_students,
        'paginated_students': paginated_students,
        'BRIGHTSPACE_ENABLED': settings.BRIGHTSPACE_ENABLED,
        'total_enrolled': enrolled_students_list.count(),
        'total_available': available_students.count()
    }
    
    return render(request, 'instructor/add_forms/section_student.html', context)

@login_required
def section_remove_students(request, section_id):
    section = get_object_or_404(Sections, id=section_id)
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=request.user).exists()
    is_coordinator = section.course.coordinator == request.user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to remove students from this section.')
        return redirect('section_dashboard', section_id=section_id)
    
    if request.method == 'POST':
        students_to_remove = request.POST.getlist('remove_students')
        if students_to_remove:
            removed_count = Enrollments.objects.filter(
                section_id=section,
                user_id__id__in=students_to_remove
            ).delete()[0]
            messages.success(request, f'Successfully removed {removed_count} student(s) from the section.')
    
    return redirect('section_student', section_id=section_id)

def password_reset_request(request):
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user']
            request.session['reset_user_id'] = user.id
            return redirect('password_reset')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = PasswordResetRequestForm()
    
    return render(request, 'registration/password_reset_request.html', {'form': form})

def password_reset(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        messages.error(request, 'Invalid password reset request. Please try again.')
        return redirect('password_reset_request')
    
    try:
        user = Users.objects.get(id=user_id)
    except Users.DoesNotExist:
        messages.error(request, 'User not found. Please try again.')
        return redirect('password_reset_request')
    
    if request.method == 'POST':
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            user.set_password(new_password)
            user.save()
            del request.session['reset_user_id']
            messages.success(request, 'Password has been reset successfully. Please login with your new password.')
            return redirect('login')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = PasswordResetForm()
    
    return render(request, 'registration/password_reset.html', {'form': form})

def login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user']
            
            if user.last_login is None:
                request.session['reset_user_id'] = user.id
                auth_login(request, user)
                messages.warning(request, 'Please set a password to continue.')
                return redirect('password_reset')
            else:
                auth_login(request, user)
                messages.success(request, f'Welcome back {user.first_name}!')
                return redirect('index')
        else:
            messages.error(request, 'Invalid username or password')
    else:
        form = LoginForm()
    
    return render(request, 'registration/login.html', {'form': form})

@login_required
def edit_assignment(request, assignment_id):
    current_user = request.user
    assignment = get_object_or_404(Assignments.objects.select_related(
        'section_id',
        'section_id__course',
        'section_id__course__department',
        'section_id__term'
    ), id=assignment_id)
    
    section = assignment.section_id
    
    is_instructor = SectionInstructors.objects.filter(section_id=section, user_id=current_user).exists()
    is_coordinator = section.course.coordinator == current_user
    
    if not (is_instructor or is_coordinator):
        messages.error(request, 'You do not have permission to edit this assignment.')
        return redirect('section_dashboard', section_id=section.id)

    if request.method == 'POST':
        form = AssignmentEditForm(request.POST, instance=assignment)
        if form.is_valid():
            form.save()
            messages.success(request, 'Assignment updated successfully.')
            return redirect('section_dashboard', section_id=section.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.title()}: {error}")
    else:
        form = AssignmentEditForm(instance=assignment)
    
    context = {
        'assignment': assignment,
        'form': form,
        'section': section
    }
    
    return redirect('section_dashboard', section_id=section.id)

@login_required
def edit_course(request, course_id):
    current_user = request.user
    course = get_object_or_404(Courses.objects.select_related(
        'department',
        'coordinator'
    ), id=course_id)
    
    is_depthead = Departments.objects.filter(department_head=current_user).exists()
    is_coordinator = course.coordinator == current_user
    
    if not (is_depthead or is_coordinator):
        messages.error(request, 'You do not have permission to edit this course.')
        return redirect('index')

    if request.method == 'POST':
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, 'Course updated successfully.')
            return redirect('index')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.title()}: {error}")
    else:
        form = CourseForm(instance=course)
    
    departments = Departments.objects.all()
    instructors = Users.objects.filter(is_instructor=True)
    
    context = {
        'course': course,
        'form': form,
        'departments': departments,
        'instructors': instructors
    }
    
    return render(request, 'instructor/add_forms/edit_course.html', context)

@login_required
def delete_course(request, course_id):
    current_user = request.user
    course = get_object_or_404(Courses.objects.select_related(
        'department',
        'coordinator'
    ), id=course_id)
    
    is_depthead = Departments.objects.filter(department_head=current_user).exists()
    is_coordinator = course.coordinator == current_user
    
    if not (is_depthead or is_coordinator):
        messages.error(request, 'You do not have permission to delete this course.')
        return redirect('index')
    
    if request.method == 'POST':
        try:
            sections_count = Sections.objects.filter(course=course).count()
            assignments_count = Assignments.objects.filter(section_id__course=course).count()
            evaluations_count = Evaluations.objects.filter(assignment_id__section_id__course=course).count()
            enrollments_count = Enrollments.objects.filter(section_id__course=course).count()
            groups_count = Groups.objects.filter(section_id__course=course).count()
            
            course.delete()
            
            messages.success(request, f'Course deleted successfully.')
            messages.info(request, f'Deleted {sections_count} sections')
            messages.info(request, f'Deleted {assignments_count} assignments')
            messages.info(request, f'Deleted {evaluations_count} evaluations')
            messages.info(request, f'Deleted {enrollments_count} enrollments')
            messages.info(request, f'Deleted {groups_count} groups')
        except Exception as e:
            messages.error(request, f'Error deleting course: {str(e)}')
    
    return redirect('index')

def bad_request(request, exception):
    return render(request, '400.html', status=400)

def permission_denied(request, exception):
    return render(request, '403.html', status=403)

def page_not_found(request, exception):
    return render(request, '404.html', status=404)

def server_error(request):
    return render(request, '500.html', status=500)

@login_required
def section_manage_instructors(request, section_id):
    section = get_object_or_404(Sections.objects.select_related('course', 'course__department', 'term'), id=section_id)
    
    if not request.user.is_superuser and not SectionInstructors.objects.filter(section_id=section, user_id=request.user).exists():
        messages.error(request, "You don't have permission to manage instructors for this section.")
        return redirect('index')
    
    current_instructors = SectionInstructors.objects.filter(section_id=section).select_related('user_id')
    available_instructors = Users.objects.filter(is_instructor=True).exclude(
        id__in=current_instructors.values_list('user_id__id', flat=True)
    )
    
    if request.method == 'POST':
        form = SectionAddInstructorForm(request.POST, section=section)
        if form.is_valid():
            form.save(request.user)
            messages.success(request, 'Instructors added successfully.')
            return redirect('section_manage_instructors', section_id=section.id)
    else:
        form = SectionAddInstructorForm(section=section)
    
    return render(request, 'instructor/add_forms/section_instructor.html', {
        'section': section,
        'current_instructors': current_instructors,
        'available_instructors': available_instructors,
        'form': form
    })

@login_required
def section_remove_instructors(request, section_id):
    section = get_object_or_404(Sections, id=section_id)
    
    if not request.user.is_superuser and not SectionInstructors.objects.filter(section_id=section, user_id=request.user).exists():
        messages.error(request, "You don't have permission to manage instructors for this section.")
        return redirect('index')
    
    if request.method == 'POST':
        instructor_ids = request.POST.getlist('remove_instructors')
        if instructor_ids:
            SectionInstructors.objects.filter(
                section_id=section,
                user_id__id__in=instructor_ids
            ).delete()
            messages.success(request, 'Instructors removed successfully.')
    
    return redirect('section_manage_instructors', section_id=section.id)

@login_required
def edit_student(request, username):
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to edit students.')
        return redirect('index')
        
    try:
        student = Users.objects.get(username=username)
        
        if request.method == 'POST':
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            
            student.first_name = first_name
            student.last_name = last_name
            student.save()
            
            messages.success(request, f'Student {student.get_full_name()} has been updated successfully.')
            return redirect('student_profile', username=student.username)
            
    except Users.DoesNotExist:
        messages.error(request, 'Student not found.')
        return redirect('index')

@login_required
def delete_student(request, username):
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to delete students.')
        return redirect('index')
        
    try:
        student = Users.objects.get(username=username)
        
        if request.method == 'POST':
            student.delete()
            messages.success(request, f'Student {student.get_full_name()} has been deleted successfully.')
            return redirect('index')
            
    except Users.DoesNotExist:
        messages.error(request, 'Student not found.')
        return redirect('index')

@login_required
def edit_evaluation(request, eval_id):
    evaluation = get_object_or_404(Evaluations, id=eval_id)
    
    is_evaluator = request.user == evaluation.evaluator_id
    
    now = timezone.now()
    assignment_active = evaluation.assignment_id.available_date <= now and evaluation.assignment_id.due_date >= now
    
    evaluation.assignment_id.assignment_active = assignment_active
    
    is_instructor = SectionInstructors.objects.filter(
        section_id=evaluation.assignment_id.section_id, 
        user_id=request.user
    ).exists()
    
    has_permission = (request.user.is_superuser or 
                    is_instructor or
                    (is_evaluator and assignment_active))
    
    if not has_permission:
        if is_evaluator and not assignment_active:
            messages.error(request, "You can only edit your evaluation while the assignment is active.")
        else:
            messages.error(request, "You don't have permission to edit this evaluation.")
        return redirect('evaluation_view', eval_id=eval_id)
    
    if request.method == 'POST':
        try:
            is_self_evaluation = evaluation.evaluator_id == evaluation.evaluatee_id
            max_allowed_points = evaluation.assignment_id.max_points_self if is_self_evaluation else evaluation.assignment_id.max_points_partner
            new_points = int(request.POST.get('points', 0))
            
            if is_evaluator and assignment_active:
                enrollment = Enrollments.objects.get(
                    user_id=request.user,
                    section_id=evaluation.assignment_id.section_id
                )
                
                if enrollment.group:
                    group_members = Enrollments.objects.filter(
                        group=enrollment.group
                    ).count()
                    
                    student_evaluations = Evaluations.objects.filter(
                        evaluator_id=request.user,
                        assignment_id=evaluation.assignment_id
                    ).exclude(id=evaluation.id)
                    
                    total_points = new_points + sum(e.points for e in student_evaluations)
                    
                    max_total_points = evaluation.assignment_id.max_points_self * group_members
                    
                    if total_points > max_total_points:
                        messages.error(request, f"Total points ({total_points}) cannot exceed maximum allowed ({max_total_points})")
                        return redirect('evaluation_view', eval_id=eval_id)
            
            if new_points > max_allowed_points:
                messages.error(request, f"Points cannot exceed {max_allowed_points} for {'self' if is_self_evaluation else 'peer'} evaluation.")
                return redirect('evaluation_view', eval_id=eval_id)
            
            comments = request.POST.get('comments', '').strip()
            if new_points != max_allowed_points and not comments:
                messages.error(request, "Comments are required when score is not 100%.")
                return redirect('evaluation_view', eval_id=eval_id)
            
            evaluation.points = new_points
            evaluation.comments = comments
            evaluation.save()
            
            if evaluation.assignment_id.enable_merits:
                try:
                    merit_scores = MeritScores.objects.get(evaluation_id=evaluation)
                    merit_fields = [
                        'score_workcontribution',
                        'score_teaminteraction',
                        'score_teamawareness',
                        'score_qualityofwork',
                        'score_knowledgeandskills'
                    ]
                    
                    for field in merit_fields:
                        value = request.POST.get(field)
                        if value:
                            setattr(merit_scores, field, int(value))
                    
                    merit_scores.save()
                except MeritScores.DoesNotExist:
                    merit_data = {}
                    merit_fields = [
                        'score_workcontribution',
                        'score_teaminteraction',
                        'score_teamawareness',
                        'score_qualityofwork',
                        'score_knowledgeandskills'
                    ]
                    
                    if all(request.POST.get(field) for field in merit_fields):
                        for field in merit_fields:
                            merit_data[field] = int(request.POST.get(field))
                        
                        MeritScores.objects.create(
                            evaluation_id=evaluation,
                            **merit_data
                        )
            
            messages.success(request, "Evaluation updated successfully.")
            return redirect('evaluation_view', eval_id=eval_id)
        except Exception as e:
            messages.error(request, f"Error updating evaluation: {str(e)}")
    
    return redirect('evaluation_view', eval_id=eval_id)

@login_required
def delete_evaluation(request, eval_id):
    evaluation = get_object_or_404(Evaluations, id=eval_id)
    
    is_instructor = SectionInstructors.objects.filter(
        section_id=evaluation.assignment_id.section_id,
        user_id=request.user
    ).exists()
    
    if not (request.user.is_superuser or 
            request.user == evaluation.evaluator_id or 
            is_instructor):
        messages.error(request, "You don't have permission to delete this evaluation.")
        return redirect('evaluation_view', eval_id=eval_id)
    
    if request.method == 'POST':
        try:
            MeritScores.objects.filter(evaluation_id=evaluation).delete()
            evaluation.delete()
            messages.success(request, "Evaluation deleted successfully.")
            return redirect('student_profile', username=evaluation.evaluatee_id.username)
        except Exception as e:
            messages.error(request, f"Error deleting evaluation: {str(e)}")
    
    return redirect('evaluation_view', eval_id=eval_id)

