# mindset_api/management/commands/seed_social_features.py

from django.core.management.base import BaseCommand
from mindset_api.models import (
    MoodPlaylist,
    JournalPrompt,
    CampusEvent
)
from datetime import date


class Command(BaseCommand):
    help = 'Seed social features data (playlists, prompts, events)'
    
    def handle(self, *args, **kwargs):
        """
        Main function that runs when you execute:
        python manage.py seed_social_features
        """
        
        self.stdout.write('🌱 Starting to seed data...\n')
        
        # Seed each type of data
        self.seed_mood_playlists()
        self.seed_journal_prompts()
        self.seed_campus_events()
        
        self.stdout.write(self.style.SUCCESS('\n✅ All data seeded successfully!'))
    
    
    def seed_mood_playlists(self):
        """Seed Spotify mood playlists"""
        
        self.stdout.write('📻 Seeding mood playlists...')
        
        playlists = [
            # Anxious mood
            {
                'mood': 'anxious',
                'name': 'Calm Down - Lo-fi Beats',
                'description': 'Gentle lo-fi beats to slow your thoughts',
                'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DWWQRwui0ExPn',
                'spotify_playlist_id': '37i9dQZF1DWWQRwui0ExPn',
                'genre': 'Lo-fi',
                'energy_level': 'low'
            },
            {
                'mood': 'anxious',
                'name': 'Deep Focus',
                'description': 'Instrumental music for concentration',
                'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DX8NTLI2TtZa6',
                'spotify_playlist_id': '37i9dQZF1DX8NTLI2TtZa6',
                'genre': 'Instrumental',
                'energy_level': 'low'
            },
            
            # Sad mood
            {
                'mood': 'sad',
                'name': 'It\'s Okay to Not Be Okay',
                'description': 'Sad songs when you need to feel your feelings',
                'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DX7qK8ma5wgG1',
                'spotify_playlist_id': '37i9dQZF1DX7qK8ma5wgG1',
                'genre': 'Pop/Indie',
                'energy_level': 'low'
            },
            {
                'mood': 'sad',
                'name': 'Uplifting Anthems',
                'description': 'When you\'re ready to feel better',
                'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DX3rxVfibe1L0',
                'spotify_playlist_id': '37i9dQZF1DX3rxVfibe1L0',
                'genre': 'Pop',
                'energy_level': 'medium'
            },
            
            # Stressed mood
            {
                'mood': 'stressed',
                'name': 'Nature Sounds - Rain & Ocean',
                'description': 'Natural sounds for instant calm',
                'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DWXe9gFZP0gtP',
                'spotify_playlist_id': '37i9dQZF1DWXe9gFZP0gtP',
                'genre': 'Nature/Ambient',
                'energy_level': 'low'
            },
            
            # Motivated mood
            {
                'mood': 'motivated',
                'name': 'Beast Mode',
                'description': 'High-energy motivation',
                'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DX76Wlfdnj7AP',
                'spotify_playlist_id': '37i9dQZF1DX76Wlfdnj7AP',
                'genre': 'Hip-Hop',
                'energy_level': 'high'
            },
            
            # Calm mood
            {
                'mood': 'calm',
                'name': 'Peaceful Piano',
                'description': 'Relaxing piano music',
                'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DX4sWSpwq3LiO',
                'spotify_playlist_id': '37i9dQZF1DX4sWSpwq3LiO',
                'genre': 'Classical',
                'energy_level': 'low'
            },
        ]
        
        created_count = 0
        
        for playlist_data in playlists:
            # Use get_or_create to avoid duplicates
            playlist, created = MoodPlaylist.objects.get_or_create(
                spotify_playlist_id=playlist_data['spotify_playlist_id'],
                defaults=playlist_data  # Only use these values if creating new
            )
            
            if created:
                created_count += 1
                self.stdout.write(f'  ✓ Created: {playlist.name}')
            else:
                self.stdout.write(f'  - Already exists: {playlist.name}')
        
        self.stdout.write(self.style.SUCCESS(f'  ✅ {created_count} playlists created\n'))
    
    
    def seed_journal_prompts(self):
        """Seed journal prompts for daily rotation"""
        
        self.stdout.write('📝 Seeding journal prompts...')
        
        prompts = [
            # Gratitude prompts
            {
                'category': 'gratitude',
                'prompt_text': 'What\'s one thing that made you smile today, even if it was small?',
                'difficulty': 'easy'
            },
            {
                'category': 'gratitude',
                'prompt_text': 'Who\'s someone you\'re grateful for right now, and why?',
                'difficulty': 'moderate'
            },
            {
                'category': 'gratitude',
                'prompt_text': 'What\'s something about yourself you appreciate today?',
                'difficulty': 'moderate'
            },
            
            # Reflection prompts
            {
                'category': 'reflection',
                'prompt_text': 'What did you learn about yourself this week?',
                'difficulty': 'moderate'
            },
            {
                'category': 'reflection',
                'prompt_text': 'If you could give advice to yourself from one year ago, what would you say?',
                'difficulty': 'deep'
            },
            {
                'category': 'reflection',
                'prompt_text': 'What\'s one thing you did today that you\'re proud of?',
                'difficulty': 'easy'
            },
            
            # Challenges prompts
            {
                'category': 'challenges',
                'prompt_text': 'What\'s one thing that felt hard today? How did you handle it?',
                'difficulty': 'moderate'
            },
            {
                'category': 'challenges',
                'prompt_text': 'What\'s a challenge you\'re facing right now? What\'s one small step you could take?',
                'difficulty': 'moderate'
            },
            {
                'category': 'challenges',
                'prompt_text': 'What\'s been weighing on your mind lately?',
                'difficulty': 'deep'
            },
            
            # Self-care prompts
            {
                'category': 'self_care',
                'prompt_text': 'What does your body need right now? Rest, movement, nourishment, or something else?',
                'difficulty': 'easy'
            },
            {
                'category': 'self_care',
                'prompt_text': 'What\'s one way you took care of yourself today?',
                'difficulty': 'easy'
            },
            {
                'category': 'self_care',
                'prompt_text': 'If you could do anything relaxing right now, what would it be?',
                'difficulty': 'easy'
            },
            
            # Emotions prompts
            {
                'category': 'emotions',
                'prompt_text': 'What emotion are you feeling most strongly right now? Where do you feel it in your body?',
                'difficulty': 'moderate'
            },
            {
                'category': 'emotions',
                'prompt_text': 'What would you tell a friend who was feeling exactly how you feel right now?',
                'difficulty': 'deep'
            },
            {
                'category': 'emotions',
                'prompt_text': 'What do you need to hear right now?',
                'difficulty': 'moderate'
            },
            
            # Goals prompts
            {
                'category': 'goals',
                'prompt_text': 'What\'s one small thing you want to accomplish tomorrow?',
                'difficulty': 'easy'
            },
            {
                'category': 'goals',
                'prompt_text': 'What\'s something you\'re looking forward to?',
                'difficulty': 'easy'
            },
            
            # Relationships prompts
            {
                'category': 'relationships',
                'prompt_text': 'Who made you feel seen or heard today?',
                'difficulty': 'easy'
            },
            {
                'category': 'relationships',
                'prompt_text': 'What\'s a relationship in your life that brings you joy?',
                'difficulty': 'moderate'
            },
        ]
        
        created_count = 0
        
        for prompt_data in prompts:
            # Check if this exact prompt already exists
            prompt, created = JournalPrompt.objects.get_or_create(
                prompt_text=prompt_data['prompt_text'],
                defaults=prompt_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(f'  ✓ Created: {prompt.prompt_text[:50]}...')
            else:
                self.stdout.write(f'  - Already exists: {prompt.prompt_text[:50]}...')
        
        self.stdout.write(self.style.SUCCESS(f'  ✅ {created_count} prompts created\n'))
    
    
    def seed_campus_events(self):
        """Seed campus calendar events"""
        
        self.stdout.write('📅 Seeding campus events...')
        
        # NOTE: Update these dates to match your actual academic calendar!
        events = [
            {
                'event_type': 'finals',
                'title': 'Fall 2025 Finals Week',
                'description': 'Final exams for fall semester',
                'start_date': date(2025, 12, 8),
                'end_date': date(2025, 12, 15),
                'typical_stress_level': 'very_high',
                'is_campus_wide': True,
                'pre_event_support': 'Create a study schedule. Stock up on healthy snacks. Plan breaks. Get enough sleep.',
                'during_event_support': 'Extra daily check-ins. Breathing exercise reminders. Campus counseling walk-ins available 9 AM - 9 PM.'
            },
            {
                'event_type': 'midterms',
                'title': 'Fall 2025 Midterms',
                'description': 'Mid-semester exams',
                'start_date': date(2025, 10, 13),
                'end_date': date(2025, 10, 20),
                'typical_stress_level': 'high',
                'is_campus_wide': True,
                'pre_event_support': 'Review your notes. Form study groups. Reach out to professors during office hours.',
                'during_event_support': 'Daily mood boosters. Connect with study buddies. Take regular breaks.'
            },
            {
                'event_type': 'registration',
                'title': 'Spring 2026 Course Registration',
                'description': 'Registration for spring semester courses',
                'start_date': date(2025, 11, 1),
                'end_date': date(2025, 11, 5),
                'typical_stress_level': 'moderate',
                'is_campus_wide': True,
                'pre_event_support': 'Plan your schedule in advance. Have backup courses ready. Set registration time reminders.',
                'during_event_support': 'Remember: if you don\'t get your first choice, there are always good alternatives!'
            },
            {
                'event_type': 'break_start',
                'title': 'Winter Break Begins',
                'description': 'Fall semester ends, winter break starts',
                'start_date': date(2025, 12, 16),
                'end_date': date(2025, 12, 16),
                'typical_stress_level': 'low',
                'is_campus_wide': True,
                'pre_event_support': 'Plan something fun for break! Reconnect with home friends.',
                'during_event_support': 'Enjoy your well-deserved rest! 🎉'
            },
            {
                'event_type': 'break_end',
                'title': 'Spring Semester Begins',
                'description': 'Welcome back! Spring semester starts',
                'start_date': date(2026, 1, 15),
                'end_date': date(2026, 1, 15),
                'typical_stress_level': 'moderate',
                'is_campus_wide': True,
                'pre_event_support': 'Ease back into routine. Don\'t overcommit in week 1.',
                'during_event_support': 'Take it one day at a time. You\'ve got this! 💪'
            },
        ]
        
        created_count = 0
        
        for event_data in events:
            # Use unique combination of type and start_date to avoid duplicates
            event, created = CampusEvent.objects.get_or_create(
                event_type=event_data['event_type'],
                start_date=event_data['start_date'],
                defaults=event_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(f'  ✓ Created: {event.title}')
            else:
                self.stdout.write(f'  - Already exists: {event.title}')
        
        self.stdout.write(self.style.SUCCESS(f'  ✅ {created_count} events created\n'))