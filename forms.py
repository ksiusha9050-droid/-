from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Логин", widget=forms.TextInput(attrs={"autofocus": True}))
    password = forms.CharField(label="Пароль", strip=False, widget=forms.PasswordInput)

class RegisterForm(UserCreationForm):
    display_name = forms.CharField(
        label="Имя и фамилия", max_length=100,
        help_text="Так вас увидит администратор в отчётах",
    )

    class Meta:
        model = User
        fields = ("username", "display_name")
        labels = {"username": "Логин"}
        help_texts = {"username": "Латиница, цифры и @ . + - _"}

class PlainForm(forms.Form):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)

class ProfileForm(PlainForm):
    name = forms.CharField(label="Имя и фамилия", max_length=100)

class ProjectForm(PlainForm):
    name = forms.CharField(label="Название проекта", max_length=100,
                           widget=forms.TextInput(attrs={"placeholder": "Например, Мобильное приложение"}))