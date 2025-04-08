from django.contrib import admin
from src.models import Users, Terms, Departments, Courses, Sections, SectionInstructors, Groups, Enrollments, Assignments, Evaluations, MeritScores

admin.site.site_header = 'PeerEval Administration'
admin.site.site_title = 'PeerEval Admin'

admin.site.register(Terms)
admin.site.register(Users)
admin.site.register(Departments)
admin.site.register(Courses)
admin.site.register(Sections)
admin.site.register(SectionInstructors)
admin.site.register(Groups)
admin.site.register(Enrollments)
admin.site.register(Assignments)
admin.site.register(Evaluations)
admin.site.register(MeritScores)


