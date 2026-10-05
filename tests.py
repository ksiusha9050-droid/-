import io
from django.contrib.auth.models import User as Account
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse
from .models import Profile
from .services import get_tracker, reset_tracker

class SiteTestCase(TransactionTestCase):
    def setUp(self):
        self.tracker = get_tracker()
        db = self.tracker.db
        for table in ("checks", "pauses", "link_codes", "sessions", "users"):
            db.execute(f"DELETE FROM {table}")
        self.project = self.tracker.projects.list_active()[0]

    def tearDown(self):
        reset_tracker()

    def register(self, login, name):
        return self.client.post(reverse("register"), {
            "username": login, "display_name": name,
            "password1": "S3cret-pass", "password2": "S3cret-pass",
        })

    def employee(self, login):
        profile = Profile.objects.get(user__username=login)
        return self.tracker.users.get(profile.tracker_user_id)

    def issue_check(self, user):
        session = self.tracker.current_session(user)
        self.tracker.sessions.update(session.id, next_check_at=self.tracker.now() - 1)
        self.tracker.tick()
        return self.tracker.pending_check(self.tracker.current_session(user))

class RegistrationTests(SiteTestCase):
    def test_first_user_becomes_admin(self):
        self.register("boss", "Анна Начальник")
        self.client.logout()
        self.register("worker", "Иван Работник")
        self.assertTrue(self.employee("boss").is_admin)
        self.assertFalse(self.employee("worker").is_admin)
        self.assertEqual(self.employee("worker").origin, "web")

    def test_pages_require_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("login") + "?next=" + reverse("dashboard"))

class WorkFlowTests(SiteTestCase):
    def setUp(self):
        super().setUp()
        self.register("boss", "Анна")
        self.client.logout()
        self.register("ivan", "Иван")
        self.user = self.employee("ivan")

    def test_start_pause_resume_stop(self):
        self.client.post(reverse("session_action", args=["start"]), {"project": self.project.id})
        self.assertEqual(self.tracker.current_session(self.user).status, "active")
        self.client.post(reverse("session_action", args=["pause"]))
        self.assertEqual(self.tracker.current_session(self.user).status, "paused")
        self.client.post(reverse("session_action", args=["resume"]))
        response = self.client.post(reverse("session_action", args=["stop"]))
        self.assertIsNone(self.tracker.current_session(self.user))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/sessions/", response.url)

    def test_api_state_and_correct_answer(self):
        self.client.post(reverse("session_action", args=["start"]), {"project": self.project.id})
        check = self.issue_check(self.user)
        state = self.client.get(reverse("api_state")).json()
        self.assertEqual(state["check"]["id"], check.id)
        self.assertNotIn("answer", state["check"])

        index = check.option_list.index(check.answer)
        data = self.client.post(reverse("api_answer", args=[check.id]), {"option": index}).json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["state"]["session"]["passed"], 1)
        self.assertIsNone(data["state"]["check"])

    def test_wrong_answer_and_truancy(self):
        self.client.post(reverse("session_action", args=["start"]), {"project": self.project.id})
        for _ in range(3):
            check = self.issue_check(self.user)
            wrong = next(i for i, o in enumerate(check.option_list) if o != check.answer)
            data = self.client.post(reverse("api_answer", args=[check.id]), {"option": wrong}).json()
            self.assertFalse(data["ok"])
        self.assertIsNone(data["state"]["session"])
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Прогул")

    def test_cannot_answer_foreign_check(self):
        self.client.post(reverse("session_action", args=["start"]), {"project": self.project.id})
        check = self.issue_check(self.user)
        self.client.logout()
        self.client.login(username="boss", password="S3cret-pass")
        response = self.client.post(reverse("api_answer", args=[check.id]), {"option": 0})
        self.assertEqual(response.status_code, 400)

    def test_employee_cannot_open_admin_pages(self):
        for name in ("live", "team", "violations", "projects", "users", "export_csv"):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, reverse("dashboard"), msg_prefix=name)

    def test_foreign_session_hidden(self):
        self.client.post(reverse("session_action", args=["start"]), {"project": self.project.id})
        session = self.tracker.current_session(self.user)
        other = self.tracker.register_web_user("Чужой")
        own = self.client.get(reverse("session_detail", args=[session.id]))
        self.assertEqual(own.status_code, 200)
        foreign = self.tracker.sessions.create(other.id, self.project.id, self.tracker.now(), None)
        response = self.client.get(reverse("session_detail", args=[foreign.id]))
        self.assertEqual(response.status_code, 404)

    def test_link_telegram_from_profile(self):
        self.client.post(reverse("profile"), {"action": "link_code"})
        code = self.tracker.link_codes.for_user(self.user.id)["code"]
        page = self.client.get(reverse("profile"))
        self.assertContains(page, f"/link {code}")
        self.tracker.link_telegram(code, 555, "Ivan TG")
        self.assertContains(self.client.get(reverse("profile")), "Привязан")

class AdminPagesTests(SiteTestCase):
    def setUp(self):
        super().setUp()
        self.register("boss", "Анна")
        self.admin = self.employee("boss")

    def test_admin_pages_open(self):
        self.tracker.start(self.admin, self.project.id)
        for name in ("live", "team", "violations", "projects", "users", "stats", "profile"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        response = self.client.get(reverse("team") + "?period=custom&from=2026-01-01&to=2026-12-31")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("employee", args=[self.admin.id])).status_code, 200)

    def test_projects_add_and_archive(self):
        self.client.post(reverse("projects"), {"action": "add", "name": "Новый проект"})
        project = next(p for p in self.tracker.projects.list_all() if p.name == "Новый проект")
        self.client.post(reverse("projects"), {"action": "archive", "project_id": project.id})
        self.assertFalse(self.tracker.projects.get(project.id).is_active)

    def test_roles_and_last_admin(self):
        self.client.post(reverse("users"), {"user_id": self.admin.id, "role": "user"})
        self.assertTrue(self.tracker.users.get(self.admin.id).is_admin)

    def test_export_csv(self):
        self.tracker.start(self.admin, self.project.id)
        response = self.client.get(reverse("export_csv") + "?period=today")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Анна", response.content.decode("utf-8-sig"))

    def test_seed_demo(self):
        call_command("seed_demo", "--reset", "--days", "7", stdout=io.StringIO())
        self.assertTrue(Account.objects.filter(username="petr").exists())
        self.assertGreater(len(self.tracker.sessions.between(0, self.tracker.now() + 10)), 10)