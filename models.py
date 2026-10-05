import json
from datetime import datetime
from django.conf import settings
from django.db import models

SESSION_STATUSES = {
    "active": "Идёт работа",
    "paused": "Пауза",
    "finished": "Завершена",
    "terminated": "Прогул",
}

END_REASONS = {
    "user": "вручную",
    "truancy": "прогул: 3 нарушения",
    "max_duration": "превышена длительность",
    "pause_timeout": "слишком долгая пауза",
}

CHECK_STATUSES = {
    "pending": "Ожидает ответа",
    "passed": "Пройдена",
    "missed": "Пропущена",
    "failed": "Неверный ответ",
    "cancelled": "Отменена",
}

CHECK_KINDS = {"math": "Пример", "emoji": "Смайлик"}

class TimestampMixin:
    @staticmethod
    def _dt(value):
        return datetime.fromtimestamp(value) if value else None

class TrackerUser(models.Model, TimestampMixin):
    tg_id = models.BigIntegerField("Telegram ID", null=True, unique=True)
    name = models.CharField("Имя", max_length=200)
    role = models.CharField("Роль", max_length=10,
                            choices=[("user", "Сотрудник"), ("admin", "Администратор")])
    created_at = models.IntegerField("Создан (timestamp)")
    origin = models.CharField("Откуда", max_length=10,
                              choices=[("telegram", "Telegram"), ("web", "Сайт")])

    class Meta:
        managed = False
        db_table = "users"
        ordering = ["name"]
        verbose_name = "сотрудник"
        verbose_name_plural = "сотрудники"

    def __str__(self):
        return self.name

    @property
    def is_admin(self):
        return self.role == "admin"

class Project(models.Model):
    name = models.CharField("Название", max_length=200, unique=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        managed = False
        db_table = "projects"
        ordering = ["-is_active", "name"]
        verbose_name = "проект"
        verbose_name_plural = "проекты"

    def __str__(self):
        return self.name

class WorkSession(models.Model, TimestampMixin):
    user = models.ForeignKey(TrackerUser, models.DO_NOTHING, db_column="user_id",
                             related_name="work_sessions", verbose_name="Сотрудник")
    project = models.ForeignKey(Project, models.DO_NOTHING, db_column="project_id",
                                related_name="work_sessions", verbose_name="Проект")
    started_at = models.IntegerField("Начало")
    ended_at = models.IntegerField("Конец", null=True)
    status = models.CharField("Статус", max_length=12, choices=list(SESSION_STATUSES.items()))
    end_reason = models.CharField("Причина окончания", max_length=20, null=True)
    next_check_at = models.IntegerField(null=True)
    missed_count = models.IntegerField("Нарушений", default=0)
    passed_count = models.IntegerField("Проверок пройдено", default=0)
    penalty_seconds = models.IntegerField("Штраф, сек", default=0)

    class Meta:
        managed = False
        db_table = "sessions"
        ordering = ["-started_at"]
        verbose_name = "рабочая сессия"
        verbose_name_plural = "рабочие сессии"

    def __str__(self):
        return f"#{self.pk} {self.user} — {self.project}"

    @property
    def started(self):
        return self._dt(self.started_at)

    @property
    def ended(self):
        return self._dt(self.ended_at)

    @property
    def is_open(self):
        return self.status in ("active", "paused")

class Pause(models.Model):
    session = models.ForeignKey(WorkSession, models.DO_NOTHING, db_column="session_id",
                                related_name="pauses")
    started_at = models.IntegerField()
    ended_at = models.IntegerField(null=True)

    class Meta:
        managed = False
        db_table = "pauses"
        ordering = ["started_at"]

class PresenceCheck(models.Model):
    session = models.ForeignKey(WorkSession, models.DO_NOTHING, db_column="session_id",
                                related_name="checks", verbose_name="Сессия")
    kind = models.CharField("Тип", max_length=10, choices=list(CHECK_KINDS.items()))
    question = models.CharField("Вопрос", max_length=200)
    answer = models.CharField("Ответ", max_length=50)
    options = models.TextField("Варианты (JSON)")
    created_at = models.IntegerField("Выдана")
    deadline = models.IntegerField("Дедлайн")
    resolved_at = models.IntegerField("Закрыта", null=True)
    status = models.CharField("Результат", max_length=12, choices=list(CHECK_STATUSES.items()))

    class Meta:
        managed = False
        db_table = "checks"
        ordering = ["-created_at"]
        verbose_name = "проверка присутствия"
        verbose_name_plural = "проверки присутствия"

    def __str__(self):
        return f"{self.question} → {self.get_status_display()}"

    @property
    def option_list(self):
        return json.loads(self.options)

    @property
    def is_violation(self):
        return self.status in ("missed", "failed")

class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="profile", verbose_name="Учётная запись")
    tracker_user = models.OneToOneField(TrackerUser, on_delete=models.DO_NOTHING,
                                        db_constraint=False, related_name="web_profile",
                                        verbose_name="Сотрудник трекера")

    class Meta:
        verbose_name = "профиль сайта"
        verbose_name_plural = "профили сайта"

    def __str__(self):
        return f"{self.user.username} → {self.tracker_user_id}"