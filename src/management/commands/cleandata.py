from django.core.management.base import BaseCommand
from src.models import *
from django.utils import timezone
from django.db.models import Q

class Command(BaseCommand):
    help = 'Clean data older than specified years'

    def add_arguments(self, parser):
        parser.add_argument(
            '--years',
            type=int,
            default=1,
            help='Number of years to keep data (default: 1)'
        )

    def handle(self, *args, **options):
        years = options['years']
        cutoff_date = timezone.now() - timezone.timedelta(days=years*365)
        
        self.stdout.write(f'Cleaning data older than {years} years...')
        
        inactive_users = Users.objects.filter(Q(last_login__lt=cutoff_date) | Q(last_login__isnull=True))
        inactive_users_count = inactive_users.count()
        inactive_users.delete()
        self.stdout.write(f'Deleted {inactive_users_count} inactive users')
        
        evaluations_deleted = Evaluations.objects.filter(submission_date__lt=cutoff_date).delete()
        self.stdout.write(f'Deleted {evaluations_deleted[0]} evaluations')
        
        assignments_deleted = Assignments.objects.filter(due_date__lt=cutoff_date).delete()
        self.stdout.write(f'Deleted {assignments_deleted[0]} assignments')
        
        sections_deleted = Sections.objects.filter(term__end_date__lt=cutoff_date).delete()
        self.stdout.write(f'Deleted {sections_deleted[0]} sections')
        
        terms_deleted = Terms.objects.filter(end_date__lt=cutoff_date).delete()
        self.stdout.write(f'Deleted {terms_deleted[0]} terms')
        
        self.stdout.write(self.style.SUCCESS('Data cleanup completed successfully'))