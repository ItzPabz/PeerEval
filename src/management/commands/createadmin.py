from django.core.management.base import BaseCommand
from src.models import Users

class Command(BaseCommand):
    help = 'Creates an admin user for the system'

    def handle(self, *args, **options):
        self.stdout.write('Creating admin user...')
        
        self.create_admin_user()

    def create_admin_user(self):
        username = input('Enter admin username: ')
        first_name = input('Enter admin first name: ')
        last_name = input('Enter admin last name: ')
        id = input('Enter admin id: ')
        
        if Users.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'User {username} already exists.'))
            return
            
        user = Users.objects.create_user(
            username=username,
            id=id,
            password=id,
            first_name=first_name,
            last_name=last_name,
            is_staff=True,
            is_superuser=True,
            is_instructor=True
        )
        
        self.stdout.write(self.style.SUCCESS(f'Admin user {username} created successfully.'))
