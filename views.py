import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time
from django.contrib import messages
from django.contrib.auth import login
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from reports import period_bounds
from tracker import TrackerError

from .auth import admin_required, employee_required
from .forms import ProfileForm, ProjectForm, RegisterForm
from .models import (CHECK_STATUSES, PresenceCheck, Profile, TrackerUser,
                     WorkSession)
from .services import get_reports, get_tracker

PERIODS = {"today": "Сегодня", "week": "Эта неделя", "month": "Этот месяц", "custom": "Свой период"}

@dataclass
class Period:
    key: str
    title: str
    since: int
    until: int
    date_from: str = ""
    date_to: str = ""

    @property
    def query(self) -> str:
        q = f"period={self.key}"
        if self.key == "custom":
            q += f"&from={self.date_from}&to={self.date_to}"
        return q

def resolve_period(request, default: str = "week") -> Period:
    key = request.GET.get("period", default)
    now = get_tracker().now()
    if key == "custom":
        try:
            d_from = date.fromisoformat(request.GET.get("from", ""))
            d_to = date.fromisoformat(request.GET.get("to", ""))
            if d_from > d_to:
                d_from, d_to = d_to, d_from
            since = int(datetime.combine(d_from, time.min).timestamp())
            until = int(datetime.combine(d_to, time.max).timestamp())
            return Period(key, f"{d_from:%d.%m.%Y} — {d_to:%d.%m.%Y}", since, until,
                          d_from.isoformat(), d_to.isoformat())
        except ValueError:
            key = default
    if key not in PERIODS:
        key = default
    since, until = period_bounds(key, now)
    return Period(key, PERIODS[key], since, until,
                  datetime.fromtimestamp(since).date().isoformat(),
                  datetime.fromtimestamp(until).date().isoformat())

def with_worked(sessions):
    tracker = get_tracker()
    for s in sessions:
        s.worked = tracker.worked_seconds(s)
    return sessions

def run(request, action, success: str = ""):
    try:
        result = action()
    except TrackerError as exc:
        messages.error(request, str(exc))
        return None
    if success:
        messages.success(request, success)
    return result

def home(request):
    return redirect("dashboard" if request.user.is_authenticated else "login")

def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        tracker = get_tracker()
        role = "user" if tracker.users.admins() else "admin"
        employee = tracker.register_web_user(form.cleaned_data["display_name"], role)
        with transaction.atomic():
            account = form.save()
            Profile.objects.create(user=account, tracker_user_id=employee.id)
        login(request, account)
        text = "Добро пожаловать! Выберите проект и начинайте работу"
        if role == "admin":
            text += " (вы первый пользователь — у вас права администратора)"
        messages.success(request, text)
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})

def build_state(user) -> dict:
    tracker = get_tracker()
    now = tracker.now()
    session = tracker.current_session(user)
    state = {"server_now": now, "session": None, "check": None, "recent": []}
    if session is None:
        return state
    pause = tracker.sessions.open_pause(session.id)
    project = tracker.projects.get(session.project_id)
    state["session"] = {
        "id": session.id,
        "status": session.status,
        "project": project.name,
        "started_at": session.started_at,
        "worked_seconds": tracker.worked_seconds(session, now),
        "passed": session.passed_count,
        "missed": session.missed_count,
        "max_missed": tracker.settings.max_missed,
        "penalty_seconds": session.penalty_seconds,
        "pause_started_at": pause["started_at"] if pause else None,
    }
    check = tracker.pending_check(session)
    if check:
        state["check"] = {
            "id": check.id,
            "question": check.question,
            "kind": check.kind,
            "options": check.option_list,
            "deadline": check.deadline,
            "timeout": tracker.settings.check_timeout,
        }
    state["recent"] = [
        {"id": c.id, "status": c.status, "label": CHECK_STATUSES[c.status],
         "question": c.question, "at": datetime.fromtimestamp(c.created_at).strftime("%H:%M:%S")}
        for c in tracker.checks.recent_for_session(session.id, 6)
    ]
    return state

@employee_required
def dashboard(request, user):
    tracker = get_tracker()
    since, until = period_bounds("today", tracker.now())
    last_session = (WorkSession.objects.filter(user_id=user.id, ended_at__gte=since)
                    .exclude(status__in=["active", "paused"])
                    .select_related("project").order_by("-ended_at").first())
    if last_session:
        with_worked([last_session])
    return render(request, "cabinet/dashboard.html", {
        "last_session": last_session,
        "state": build_state(user),
        "projects": tracker.projects.list_active(),
        "today": get_reports().user_report(user, since, until),
        "cfg": tracker.settings,
    })

@require_POST
@employee_required
def session_action(request, user, action):
    tracker = get_tracker()
    if action == "start":
        try:
            project_id = int(request.POST.get("project", ""))
        except ValueError:
            messages.error(request, "Выберите проект")
            return redirect("dashboard")
        run(request, lambda: tracker.start(user, project_id), "Работа началась, время пошло")
    elif action == "pause":
        run(request, lambda: tracker.pause(user), "Пауза: время не идёт, проверки не приходят")
    elif action == "resume":
        run(request, lambda: tracker.resume(user), "Работа продолжается")
    elif action == "stop":
        session = run(request, lambda: tracker.stop(user))
        if session:
            messages.success(request, f"Сессия завершена, засчитано "
                                      f"{tracker.worked_seconds(session) // 60} мин")
            return redirect("session_detail", session.id)
    else:
        raise Http404
    return redirect("dashboard")

@require_GET
@employee_required
def api_state(request, user):
    return JsonResponse(build_state(user))

@require_POST
@employee_required
def api_answer(request, user, check_id):
    tracker = get_tracker()
    try:
        ok, text = tracker.answer_check(user, check_id, int(request.POST.get("option", -1)))
    except (TrackerError, ValueError) as exc:
        return JsonResponse({"ok": False, "message": str(exc), "state": build_state(user)}, status=400)
    return JsonResponse({"ok": ok, "message": text, "state": build_state(user)})

def stats_context(request, subject) -> dict:
    reports = get_reports()
    period = resolve_period(request)
    report = reports.user_report(subject, period.since, period.until)
    projects = reports.project_breakdown(subject, period.since, period.until)
    days = reports.daily_breakdown(period.since, period.until, subject)
    sessions = (WorkSession.objects
                .filter(user_id=subject.id, started_at__range=(period.since, period.until))
                .select_related("project"))
    page = Paginator(sessions, 15).get_page(request.GET.get("page"))
    with_worked(page.object_list)
    return {
        "subject": subject,
        "period": period,
        "periods": PERIODS,
        "report": report,
        "projects": projects,
        "projects_max": max(projects.values(), default=0),
        "days": days[-31:],
        "days_max": max((s for _, s in days), default=0),
        "page": page,
    }

@employee_required
def stats(request, user):
    return render(request, "cabinet/stats.html", stats_context(request, user))

@employee_required
def session_detail(request, user, session_id):
    session = get_object_or_404(WorkSession.objects.select_related("user", "project"), pk=session_id)
    if session.user_id != user.id and not user.is_admin:
        raise Http404
    with_worked([session])
    events = [{"at": session.started_at, "kind": "start", "text": "Начало работы"}]
    for p in session.pauses.all():
        events.append({"at": p.started_at, "kind": "pause", "text": "Пауза"})
        if p.ended_at:
            events.append({"at": p.ended_at, "kind": "resume", "text": "Продолжение после паузы"})
    for c in session.checks.all():
        reaction = (c.resolved_at - c.created_at
                    if c.resolved_at and c.status in ("passed", "failed") else None)
        events.append({"at": c.created_at, "kind": c.status, "check": c, "reaction": reaction,
                       "text": f"Проверка: {c.question}"})
    if session.ended_at:
        events.append({"at": session.ended_at, "kind": "end", "text": "Окончание"})
    events.sort(key=lambda e: (e["at"], e["kind"] == "end"))
    return render(request, "cabinet/session_detail.html", {"session": session, "events": events})

@employee_required
def profile(request, user):
    tracker = get_tracker()
    form = ProfileForm(request.POST or None, initial={"name": user.name})
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "rename" and form.is_valid():
            tracker.users.rename(user.id, form.cleaned_data["name"].strip())
            messages.success(request, "Имя сохранено")
            return redirect("profile")
        if action == "link_code":
            run(request, lambda: tracker.create_link_code(user))
            return redirect("profile")
        if action == "unlink":
            tracker.unlink_telegram(user)
            messages.success(request, "Telegram отвязан")
            return redirect("profile")

    code = tracker.link_codes.for_user(user.id)
    if code and code["expires_at"] < tracker.now():
        code = None
    return render(request, "cabinet/profile.html", {
        "form": form,
        "code": code,
        "bot_enabled": bool(tracker.settings.bot_token),
    })

@admin_required
def live(request, user):
    tracker = get_tracker()
    now = tracker.now()
    rows = with_worked(list(WorkSession.objects.filter(status__in=["active", "paused"])
                            .select_related("user", "project").order_by("started_at")))
    for s in rows:
        s.pending = tracker.checks.pending_for_session(s.pk)
        if s.pending:
            s.pending_left = max(0, s.pending.deadline - now)
        pause = tracker.sessions.open_pause(s.pk)
        s.pause_for = now - pause["started_at"] if pause else None
        s.next_check_in = max(0, s.next_check_at - now) if s.next_check_at else None
    since, until = period_bounds("today", now)
    today_checks = PresenceCheck.objects.filter(created_at__range=(since, until))
    return render(request, "cabinet/live.html", {
        "rows": rows,
        "working": sum(1 for s in rows if s.status == "active"),
        "paused": sum(1 for s in rows if s.status == "paused"),
        "violations_today": today_checks.filter(status__in=["missed", "failed"]).count(),
        "passed_today": today_checks.filter(status="passed").count(),
        "truancy_today": WorkSession.objects.filter(status="terminated",
                                                    ended_at__range=(since, until)).count(),
    })

@admin_required
def team(request, user):
    reports = get_reports()
    period = resolve_period(request)
    rows = reports.team_report(period.since, period.until)
    active_ids = {r.user_id for r in rows}
    idle = TrackerUser.objects.exclude(id__in=active_ids)
    return render(request, "cabinet/team.html", {
        "period": period,
        "periods": PERIODS,
        "rows": rows,
        "idle": idle,
        "rows_max": max((r.worked_seconds for r in rows), default=0),
        "total_worked": sum(r.worked_seconds for r in rows),
        "total_violations": sum(r.violations for r in rows),
        "total_truancy": sum(r.terminated for r in rows),
    })

@admin_required
def employee(request, user, user_id):
    subject = get_tracker().users.get(user_id)
    if subject is None:
        raise Http404
    context = stats_context(request, subject)
    context["admin_view"] = True
    return render(request, "cabinet/stats.html", context)

@admin_required
def violations(request, user):
    period = resolve_period(request, default="month")
    qs = (PresenceCheck.objects
          .filter(status__in=["missed", "failed"], created_at__range=(period.since, period.until))
          .select_related("session__user", "session__project"))
    who = request.GET.get("user", "")
    if who.isdigit():
        qs = qs.filter(session__user_id=int(who))
    kind = request.GET.get("kind", "")
    if kind in ("missed", "failed"):
        qs = qs.filter(status=kind)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "cabinet/violations.html", {
        "period": period,
        "periods": PERIODS,
        "page": page,
        "total": qs.count(),
        "employees": TrackerUser.objects.all(),
        "who": who,
        "kind": kind,
        "filter_query": f"{period.query}&user={who}&kind={kind}",
    })

@admin_required
def projects(request, user):
    tracker = get_tracker()
    form = ProjectForm(request.POST or None)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add" and form.is_valid():
            name = form.cleaned_data["name"].strip()
            try:
                tracker.projects.add(name)
                messages.success(request, f"Проект «{name}» добавлен")
            except sqlite3.IntegrityError:
                messages.error(request, "Проект с таким названием уже есть")
            return redirect("projects")
        project_id = int(request.POST.get("project_id", 0) or 0)
        if action == "archive":
            tracker.projects.archive(project_id)
            messages.success(request, "Проект отправлен в архив")
            return redirect("projects")
        if action == "restore":
            tracker.projects.restore(project_id)
            messages.success(request, "Проект снова активен")
            return redirect("projects")

    stats = {row["project_id"]: row for row in
             WorkSession.objects.values("project_id")
             .annotate(sessions=Count("id"), last=Max("started_at"))}
    items = tracker.projects.list_all()
    for p in items:
        p.sessions = stats.get(p.id, {}).get("sessions", 0)
        p.last = stats.get(p.id, {}).get("last")
    return render(request, "cabinet/projects.html", {"form": form, "items": items})

@admin_required
def users(request, user):
    tracker = get_tracker()
    if request.method == "POST":
        target = int(request.POST.get("user_id", 0) or 0)
        role = request.POST.get("role", "")
        updated = run(request, lambda: tracker.set_role(target, role))
        if updated:
            messages.success(request, f"{updated.name}: "
                                      f"{'администратор' if updated.is_admin else 'сотрудник'}")
        return redirect("users")
    logins = dict(Profile.objects.values_list("tracker_user_id", "user__username"))
    items = list(TrackerUser.objects.annotate(sessions=Count("work_sessions"),
                                              last=Max("work_sessions__started_at")))
    for u in items:
        u.login = logins.get(u.id)
    return render(request, "cabinet/users.html", {"items": items, "me": user})

@admin_required
def export_csv(request, user):
    period = resolve_period(request, default="month")
    data = get_reports().export_csv(period.since, period.until)
    response = HttpResponse(data.encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
    name = f"timetracker {period.date_from} {period.date_to}.csv"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response