from django import forms
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from src.models import Users, Evaluations, MeritScores, Assignments, Courses, Departments, Sections, SectionInstructors, Terms, Enrollments, Groups
from django.db import models

class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=64,
        widget=forms.TextInput(attrs={'placeholder': 'Username'})
    )
    password = forms.CharField(
        max_length=128,
        widget=forms.PasswordInput(attrs={'placeholder': 'Password'})
    )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if username and password:
            user = authenticate(username=username, password=password)
            if user is None:
                raise ValidationError('Invalid username or password')
            cleaned_data['user'] = user

        return cleaned_data

class EvaluationForm(forms.ModelForm):
    evaluated_index = forms.IntegerField(
        min_value=1,
        required=True,
        widget=forms.HiddenInput()
    )
    points = forms.IntegerField(
        min_value=0,
        max_value=120,
        required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    comments = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4
        })
    )
    
    score_workcontribution = forms.ChoiceField(
        choices=[(str(i), str(i)) for i in range(1, 6)],
        required=False,
        widget=forms.RadioSelect(attrs={'class': 'hidden'})
    )
    score_teaminteraction = forms.ChoiceField(
        choices=[(str(i), str(i)) for i in range(1, 6)],
        required=False,
        widget=forms.RadioSelect(attrs={'class': 'hidden'})
    )
    score_teamawareness = forms.ChoiceField(
        choices=[(str(i), str(i)) for i in range(1, 6)],
        required=False,
        widget=forms.RadioSelect(attrs={'class': 'hidden'})
    )
    score_qualityofwork = forms.ChoiceField(
        choices=[(str(i), str(i)) for i in range(1, 6)],
        required=False,
        widget=forms.RadioSelect(attrs={'class': 'hidden'})
    )
    score_knowledgeandskills = forms.ChoiceField(
        choices=[(str(i), str(i)) for i in range(1, 6)],
        required=False,
        widget=forms.RadioSelect(attrs={'class': 'hidden'})
    )

    class Meta:
        model = Evaluations
        fields = ['points', 'comments']

    def __init__(self, *args, assignment=None, group_members=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assignment = assignment
        self.group_members = group_members or []
        
        if assignment:
            self.fields['points'].max_value = assignment.max_points_partner

    def clean(self):
        cleaned_data = super().clean()
        evaluated_index = cleaned_data.get('evaluated_index')
        points = cleaned_data.get('points')
        
        if evaluated_index < 1 or evaluated_index > len(self.group_members):
            raise ValidationError('Invalid evaluation index')
            
        evaluated_user = self.group_members[evaluated_index - 1].user_id
        total_points = 0
        for i in range(1, len(self.group_members) + 1):
            if i == evaluated_index:
                total_points += points
            else:
                other_points = self.data.get(f'points_{i}')
                if other_points:
                    try:
                        total_points += int(other_points)
                    except (ValueError, TypeError):
                        continue

        max_total_points = self.assignment.max_points_self * len(self.group_members)
        if total_points > max_total_points:
            raise ValidationError(f'Total points ({total_points}) cannot exceed maximum allowed ({max_total_points})')
        
        cleaned_data['evaluatee'] = evaluated_user
        
        return cleaned_data

    def save(self, commit=True, evaluator=None):
        instance = super().save(commit=False)
        instance.evaluator = evaluator
        instance.evaluatee = self.cleaned_data['evaluatee']
        instance.assignment = self.assignment
        
        if commit:
            instance.save()
            
            if self.assignment.enable_merits:
                merit_fields = [
                    'score_workcontribution',
                    'score_teaminteraction',
                    'score_teamawareness',
                    'score_qualityofwork',
                    'score_knowledgeandskills'
                ]
                
                for field in merit_fields:
                    if self.cleaned_data.get(field):
                        MeritScores.objects.create(
                            evaluation=instance,
                            category=field.replace('score_', ''),
                            score=int(self.cleaned_data[field])
                        )
        
        return instance

class CourseForm(forms.ModelForm):
    department = forms.ModelChoiceField(
        queryset=Departments.objects.all(),
        required=True,
        empty_label="Select Department"
    )
    course_code = forms.CharField(
        max_length=16,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': '101, 17600, 201A, etc.'})
    )
    name = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Introduction to Computer Science, English Composition I, etc.'})
    )
    coordinator = forms.ModelChoiceField(
        queryset=Users.objects.filter(is_instructor=True),
        required=True,
        empty_label="Select Coordinator"
    )

    class Meta:
        model = Courses
        fields = ['department', 'course_code', 'name', 'coordinator']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['coordinator'].queryset = Users.objects.filter(is_instructor=True)

    def clean(self):
        cleaned_data = super().clean()
        department = cleaned_data.get('department')
        course_code = cleaned_data.get('course_code')
        name = cleaned_data.get('name')
        coordinator = cleaned_data.get('coordinator')

        if department and course_code:
            try:
                existing_course = Courses.objects.get(department=department, course_code=course_code)
                if existing_course.id != self.instance.id:
                    if existing_course.coordinator is None:
                        existing_course.coordinator = coordinator
                        existing_course.name = name
                        existing_course.save()
                        self.coordinator_assigned = True
                        self.existing_course = existing_course
                    else:
                        coordinator = existing_course.coordinator
                        raise ValidationError(f'{department.id}{course_code} already exists in the system. {coordinator.first_name} {coordinator.last_name} is the current coordinator.')
            except Courses.DoesNotExist:
                pass

    def save(self, commit=True):
        if hasattr(self, 'coordinator_assigned'):
            return self.existing_course
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

class SectionForm(forms.ModelForm):
    course = forms.ModelChoiceField(
        queryset=Courses.objects.all(),
        required=True,
        empty_label="Select Course"
    )
    section_number = forms.CharField(
        max_length=6,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': '001, 002, etc.'})
    )
    term = forms.ModelChoiceField(
        queryset=Terms.objects.all(),
        required=True,
        empty_label="Select Term"
    )
    instructor = forms.ModelChoiceField(
        queryset=Users.objects.filter(is_instructor=True),
        required=True,
        empty_label="Select Instructor"
    )

    class Meta:
        model = Sections
        fields = ['course', 'section_number', 'term']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['instructor'].queryset = Users.objects.filter(is_instructor=True)

    def clean(self):
        cleaned_data = super().clean()
        course = cleaned_data.get('course')
        section_number = cleaned_data.get('section_number')
        term = cleaned_data.get('term')

        if course and section_number and term:
            try:
                existing_section = Sections.objects.get(
                    course=course,
                    section_number=section_number,
                    term=term
                )
                if existing_section.id != self.instance.id:
                    raise ValidationError('Section with this course, section number, and term already exists')
            except Sections.DoesNotExist:
                pass

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
            SectionInstructors.objects.create(
                section_id=instance,
                user_id=self.cleaned_data['instructor']
            )
        return instance

class AssignmentForm(forms.ModelForm):
    section_id = forms.ModelChoiceField(
        queryset=Sections.objects.all(),
        required=True,
        empty_label="Select Section"
    )
    name = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )
    available_date = forms.DateTimeField(
        required=True,
        widget=forms.DateTimeInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100', 'type': 'datetime-local'})
    )
    due_date = forms.DateTimeField(
        required=True,
        widget=forms.DateTimeInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100', 'type': 'datetime-local'})
    )
    max_points_self = forms.IntegerField(
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )
    max_points_partner = forms.IntegerField(
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )
    self_eval = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'rounded border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )
    enable_merits = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'rounded border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )

    class Meta:
        model = Assignments
        fields = ['section_id', 'name', 'available_date', 'due_date', 'max_points_self', 'max_points_partner', 'self_eval', 'enable_merits']

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

class AssignmentEditForm(forms.ModelForm):
    name = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )
    available_date = forms.DateTimeField(
        required=True,
        widget=forms.DateTimeInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100', 'type': 'datetime-local'})
    )
    due_date = forms.DateTimeField(
        required=True,
        widget=forms.DateTimeInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100', 'type': 'datetime-local'})
    )
    max_points_self = forms.IntegerField(
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )
    max_points_partner = forms.IntegerField(
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )
    self_eval = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'rounded border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )
    enable_merits = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'rounded border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )

    class Meta:
        model = Assignments
        fields = ['name', 'available_date', 'due_date', 'max_points_self', 'max_points_partner', 'self_eval', 'enable_merits']

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

class InstructorForm(forms.ModelForm):
    username = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Username'})
    )
    first_name = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Last Name'})
    )
    id = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'ID'})
    )

    class Meta:
        model = Users
        fields = ['username', 'first_name', 'last_name', 'id']

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        id = cleaned_data.get('id')

        if username:
            try:
                existing_user = Users.objects.get(username=username)
                if existing_user.id != self.instance.id:
                    raise ValidationError('Username already exists')
            except Users.DoesNotExist:
                pass

        if id:
            try:
                existing_user = Users.objects.get(id=id)
                if existing_user.id != self.instance.id:
                    raise ValidationError('ID already exists')
            except Users.DoesNotExist:
                pass

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.is_instructor = True
        if commit:
            instance.set_password(self.cleaned_data['id'])
            instance.save()
        return instance

class StudentForm(forms.ModelForm):
    username = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Username'})
    )
    first_name = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Last Name'})
    )
    id = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'ID'})
    )

    class Meta:
        model = Users
        fields = ['username', 'first_name', 'last_name', 'id']

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        id = cleaned_data.get('id')

        if username:
            try:
                existing_user = Users.objects.get(username=username)
                if existing_user.id != self.instance.id:
                    raise ValidationError('Username already exists')
            except Users.DoesNotExist:
                pass

        if id:
            try:
                existing_user = Users.objects.get(id=id)
                if existing_user.id != self.instance.id:
                    raise ValidationError('ID already exists')
            except Users.DoesNotExist:
                pass

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.is_instructor = False
        instance.id = self.cleaned_data['id']
        if commit:
            instance.set_password(self.cleaned_data['id'])
            instance.save()
        return instance

class SectionAddStudentForm(forms.Form):
    students = forms.ModelMultipleChoiceField(
        queryset=Users.objects.filter(is_instructor=False),
        required=True,
        widget=forms.SelectMultiple(attrs={
            'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'
        })
    )

    def __init__(self, *args, section=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.section = section
        if section:
            enrolled_students = Enrollments.objects.filter(section_id=section).values_list('user_id', flat=True)
            self.fields['students'].queryset = Users.objects.filter(is_instructor=False).exclude(id__in=enrolled_students)

    def save(self, instructor_user):
        students = self.cleaned_data['students']
        enrollments = []

        for student in students:
            enrollment = Enrollments(
                user_id=student,
                section_id=self.section,
                added_by=instructor_user
            )
            enrollments.append(enrollment)

        Enrollments.objects.bulk_create(enrollments)
        return enrollments

class SectionAddAssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignments
        fields = ['name', 'available_date', 'due_date', 'max_points_self', 'max_points_partner', 'self_eval', 'enable_merits']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'}),
            'available_date': forms.DateTimeInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100', 'type': 'datetime-local'}),
            'due_date': forms.DateTimeInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100', 'type': 'datetime-local'}),
            'max_points_self': forms.NumberInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'}),
            'max_points_partner': forms.NumberInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'}),
            'self_eval': forms.CheckboxInput(attrs={'class': 'rounded border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'}),
            'enable_merits': forms.CheckboxInput(attrs={'class': 'rounded border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
        }

    def __init__(self, *args, section=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.section = section

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.section_id = self.section
        if commit:
            instance.save()
        return instance

class GroupFormationMethodForm(forms.Form):
    METHODS = [
        ('random', 'Random Groups'),
        ('merit', 'Merit-Based Groups')
    ]
    
    method = forms.ChoiceField(
        choices=METHODS,
        required=True,
        error_messages={'required': 'Please select a group formation method.'},
        widget=forms.RadioSelect(attrs={'class': 'join-item btn flex-1'})
    )
    
    group_size = forms.IntegerField(
        min_value=2,
        max_value=10,
        required=True,
        error_messages={
            'required': 'Please enter a group size.',
            'min_value': 'Group size must be at least 2.',
            'max_value': 'Group size cannot exceed 10.'
        },
        initial=4,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('method')
        group_size = cleaned_data.get('group_size')
        
        if not method:
            self.add_error('method', 'Please select a group formation method.')
        if not group_size:
            self.add_error('group_size', 'Please enter a group size.')
        elif group_size < 2:
            self.add_error('group_size', 'Group size must be at least 2.')
        elif group_size > 10:
            self.add_error('group_size', 'Group size cannot exceed 10.')
            
        return cleaned_data

class PasswordResetRequestForm(forms.Form):
    first_name = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Last Name'})
    )
    username = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Username'})
    )
    id = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'ID'})
    )

    def clean_id(self):
        id = self.cleaned_data.get('id')
        try:
            return int(id)
        except ValueError:
            raise ValidationError('ID must be a number')

    def clean(self):
        cleaned_data = super().clean()
        first_name = cleaned_data.get('first_name')
        last_name = cleaned_data.get('last_name')
        username = cleaned_data.get('username')
        id = cleaned_data.get('id')

        if not all([first_name, last_name, username, id]):
            return cleaned_data

        try:
            user = Users.objects.get(
                first_name__iexact=first_name,
                last_name__iexact=last_name,
                username__iexact=username,
                id=id
            )
            cleaned_data['user'] = user
        except Users.DoesNotExist:
            raise ValidationError('No user found with the provided information')
        except Users.MultipleObjectsReturned:
            raise ValidationError('Multiple users found with the provided information. Please contact support.')

        return cleaned_data

class PasswordResetForm(forms.Form):
    new_password = forms.CharField(
        max_length=128,
        required=True,
        widget=forms.PasswordInput(attrs={'placeholder': 'New Password'})
    )
    confirm_password = forms.CharField(
        max_length=128,
        required=True,
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm Password'})
    )

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password and new_password != confirm_password:
            raise ValidationError('Passwords do not match')

        return cleaned_data

class SectionAddInstructorForm(forms.Form):
    instructors = forms.ModelMultipleChoiceField(
        queryset=Users.objects.filter(is_instructor=True),
        required=True,
        widget=forms.SelectMultiple(attrs={
            'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'
        })
    )

    def __init__(self, *args, section=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.section = section
        if section:
            current_instructors = SectionInstructors.objects.filter(section_id=section).values_list('user_id', flat=True)
            self.fields['instructors'].queryset = Users.objects.filter(is_instructor=True).exclude(id__in=current_instructors)

    def save(self, added_by_user):
        instructors = self.cleaned_data['instructors']
        section_instructors = []

        for instructor in instructors:
            section_instructor = SectionInstructors(
                user_id=instructor,
                section_id=self.section
            )
            section_instructors.append(section_instructor)

        SectionInstructors.objects.bulk_create(section_instructors)
        return section_instructors

class TermForm(forms.ModelForm):
    name = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100',
            'placeholder': 'e.g., Fall 2024, Spring 2025'
        })
    )
    start_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100',
            'type': 'date'
        })
    )
    end_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'class': 'w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100',
            'type': 'date'
        })
    )

    class Meta:
        model = Terms
        fields = ['name', 'start_date', 'end_date']

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name:
            try:
                existing_term = Terms.objects.get(name__iexact=name)
                if existing_term.id != self.instance.id:
                    raise ValidationError('A term with this name already exists')
            except Terms.DoesNotExist:
                pass
        return name

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if not all([start_date, end_date]):
            return cleaned_data

        # Check if end_date is after start_date
        if end_date <= start_date:
            raise ValidationError('End date must be after start date')

        # Check for overlapping dates
        overlapping_terms = Terms.objects.filter(
            (models.Q(start_date__lte=start_date) & models.Q(end_date__gte=start_date)) |
            (models.Q(start_date__lte=end_date) & models.Q(end_date__gte=end_date)) |
            (models.Q(start_date__gte=start_date) & models.Q(end_date__lte=end_date))
        )

        if self.instance.id:
            overlapping_terms = overlapping_terms.exclude(id=self.instance.id)

        if overlapping_terms.exists():
            raise ValidationError('This term overlaps with existing terms')

        return cleaned_data


