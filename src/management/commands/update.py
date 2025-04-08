import requests
from django.core.management.base import BaseCommand
from django.conf import settings
import subprocess
import sys
from pathlib import Path
import shutil
import tempfile

class Command(BaseCommand):
    help = 'Updates the application with the latest changes from GitHub'

    def handle(self, *args, **options):
        try:
            current_dir = Path(__file__).resolve().parent.parent.parent.parent
            
            settings_path = current_dir / 'peereval' / 'settings.py'
            if settings_path.exists():
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    shutil.copy2(settings_path, tmp.name)
                    settings_backup = tmp.name
            else:
                settings_backup = None
            
            self.stdout.write(self.style.SUCCESS('Fetching latest changes from GitHub...'))
            subprocess.run(['git', 'fetch', 'origin'], cwd=current_dir, check=True)
            
            current_branch = subprocess.check_output(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=current_dir
            ).decode().strip()
            
            local_hash = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'],
                cwd=current_dir
            ).decode().strip()
            
            remote_hash = subprocess.check_output(
                ['git', 'rev-parse', f'origin/{current_branch}'],
                cwd=current_dir
            ).decode().strip()
            
            if local_hash != remote_hash:
                self.stdout.write(
                    self.style.WARNING(
                        f'Updates available! Local: {local_hash[:7]}, Remote: {remote_hash[:7]}'
                    )
                )
                
                self.stdout.write(self.style.SUCCESS('Pulling latest changes...'))
                result = subprocess.run(
                    ['git', 'pull', 'origin', current_branch],
                    cwd=current_dir,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    if settings_backup:
                        shutil.copy2(settings_backup, settings_path)
                        self.stdout.write(self.style.SUCCESS('Preserved local settings.py'))
                    
                    self.stdout.write(self.style.SUCCESS('Successfully updated!'))
                    self.stdout.write(self.style.SUCCESS('Changes pulled:'))
                    self.stdout.write(result.stdout)
                    
                    if 'requirements.txt' in result.stdout:
                        self.stdout.write(
                            self.style.WARNING(
                                'requirements.txt has been updated. Please run: pip install -r requirements.txt'
                            )
                        )
                    
                    if any(f.endswith('.py') for f in result.stdout.split('\n') if 'migrations' in f):
                        self.stdout.write(
                            self.style.WARNING(
                                'Database migrations are available. Please run: python manage.py migrate'
                            )
                        )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'Error pulling updates: {result.stderr}')
                    )
            else:
                self.stdout.write(
                    self.style.SUCCESS('Your repository is already up to date!')
                )
                
        except subprocess.CalledProcessError as e:
            self.stdout.write(
                self.style.ERROR(f'Error during update process: {str(e)}')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Unexpected error: {str(e)}')
            )
        finally:
            if settings_backup:
                try:
                    Path(settings_backup).unlink()
                except Exception:
                    pass 