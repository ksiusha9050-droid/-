from .auth import tracker_user_for
def tracker_user(request):
    return {"tt_user": tracker_user_for(request)}
