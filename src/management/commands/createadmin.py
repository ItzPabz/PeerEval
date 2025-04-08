from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os

class Command(BaseCommand):
    help = 'Creates a superuser with the specified credentials'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Admin username')
        parser.add_argument('--password', type=str, help='Admin password')
        parser.add_argument('--email', type=str, help='Admin email')

    def handle(self, *args, **options):
        username = options.get('username') or os.getenv('ADMIN_USERNAME')
        password = options.get('password') or os.getenv('ADMIN_PASSWORD')
        email = options.get('email') or os.getenv('ADMIN_EMAIL')

        if not all([username, password, email]):
            self.stdout.write(self.style.ERROR('Missing required arguments. Please provide --username, --password, and --email'))
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'User {username} already exists'))
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f'Successfully created admin user {username}'))
