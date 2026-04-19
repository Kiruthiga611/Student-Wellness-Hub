from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import MicroCommitment
 
 
@shared_task
def send_commitment_reminders():
    """
    Send reminders for pending commitments.
    
    Runs every hour via Celery beat.
    Sends reminder if:
    - Commitment is not completed
    - Committed 2+ hours ago
    - Reminder not already sent
    """
    
    # Find commitments needing reminders
    two_hours_ago = timezone.now() - timedelta(hours=2)
    
    pending_commitments = MicroCommitment.objects.filter(
        completed_at__isnull=True,  # Not completed
        reminder_sent=False,         # Reminder not sent
        committed_at__lte=two_hours_ago  # Committed 2+ hours ago
    )
    
    reminder_count = 0
    
    for commitment in pending_commitments:
        # Send notification to user
        success = send_push_notification(
            user=commitment.user,
            title="Gentle reminder 💙",
            message=f"You committed to {commitment.get_commitment_type_display()}. Ready?",
            data={
                'type': 'commitment_reminder',
                'commitment_id': commitment.id,
                'commitment_type': commitment.commitment_type
            }
        )
        
        if success:
            # Mark reminder as sent
            commitment.reminder_sent = True
            commitment.reminder_sent_at = timezone.now()
            commitment.save()
            reminder_count += 1
    
    return f"Sent {reminder_count} commitment reminders"
 
 
@shared_task
def cleanup_old_pending_commitments():
    """
    Clean up very old pending commitments (7+ days old).
    
    Runs daily at 3 AM via Celery beat.
    Marks old pending commitments as expired/abandoned.
    """
    
    week_ago = timezone.now() - timedelta(days=7)
    
    old_commitments = MicroCommitment.objects.filter(
        completed_at__isnull=True,
        committed_at__lte=week_ago
    )
    
    count = old_commitments.count()
    
    # You could:
    # - Delete them: old_commitments.delete()
    # - Or mark as expired: old_commitments.update(expired=True)
    # For now, we'll just log them
    
    return f"Found {count} old pending commitments (7+ days)"
 
 
def send_push_notification(user, title, message, data=None):
    """
    Send push notification to user's device.
    
    Implementation depends on your notification service:
    - Firebase Cloud Messaging (FCM)
    - Apple Push Notification Service (APNS)
    - OneSignal
    - Expo Push Notifications
    
    For now, this is a placeholder.
    """
    
    # PLACEHOLDER IMPLEMENTATION
    # Replace with your actual notification service
    
    print(f"📱 Sending notification to {user.username}")
    print(f"   Title: {title}")
    print(f"   Message: {message}")
    print(f"   Data: {data}")
    
    # Example with Firebase (if you're using it):
    # from firebase_admin import messaging
    # 
    # try:
    #     # Get user's FCM token from database
    #     fcm_token = user.profile.fcm_token
    #     
    #     if fcm_token:
    #         notification = messaging.Message(
    #             notification=messaging.Notification(
    #                 title=title,
    #                 body=message
    #             ),
    #             data=data or {},
    #             token=fcm_token
    #         )
    #         
    #         response = messaging.send(notification)
    #         return True
    # except Exception as e:
    #     print(f"Notification error: {e}")
    #     return False
    
    # For development: always return True
    return True
 