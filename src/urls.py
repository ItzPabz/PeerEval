from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login, name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),
    path('password_reset_request/', views.password_reset_request, name='password_reset_request'),
    path('password_reset/', views.password_reset, name='password_reset'),
    path('evaluation/<str:department><str:course>-<str:section_number>/<int:assignment>/', views.evaluation, name='evaluation'),
    path('submit_evaluation/<str:department>/<str:course>/<str:section_number>/<int:assignment>/', views.submit_evaluation, name='submit_evaluation'),
    path('manage/<int:section_id>/', views.section_dashboard, name='section_dashboard'),
    path('manage/<int:section_id>/manage_students/', views.section_student, name='section_add_student'),
    path('manage/<int:section_id>/add_assignment/', views.section_add_assignment, name='section_add_assignment'),
    path('manage/<int:section_id>/manage_groups/', views.section_manage_groups, name='section_manage_groups'),
    path('manage/<int:section_id>/export_grades/', views.export_grades, name='export_grades'),
    path('view/student/<str:username>/', views.student_profile, name='student_profile'),
    path('view/assignment/<int:assignment_id>/', views.view_assignment, name='view_assignment'),
    path('add/course/', views.add_course, name='add_course'),
    path('add/instructor/', views.add_instructor, name='add_instructor'),
    path('add/section/', views.add_section, name='add_section'),
    path('add/assignment/', views.add_assignment, name='add_assignment'),
    path('add/student/', views.add_student, name='add_students'),
    path('add/term/', views.add_term, name='add_term'),
    path('add/department/', views.add_department, name='add_department'),
    path('view/evaluation/<int:eval_id>', views.evaluation_view, name='evaluation_view'),
    path('section/<int:section_id>/import/', views.import_wizard, name='import_wizard'),
    path('section/<int:section_id>/import/confirm/', views.import_confirm, name='import_confirm'),
    path('section/<int:section_id>/export/', views.export_grades, name='export_grades'),
    path('section/<int:section_id>/student/', views.section_student, name='section_student'),
    path('section/<int:section_id>/student/remove/', views.section_remove_students, name='section_remove_students'),
    path('assignment/<int:assignment_id>/delete', views.view_assignment, name='delete_assignment'),
    path('assignment/<int:assignment_id>/edit/', views.edit_assignment, name='edit_assignment'),
    path('course/<int:course_id>/edit/', views.edit_course, name='edit_course'),
    path('course/<int:course_id>/delete/', views.delete_course, name='delete_course'),
]

