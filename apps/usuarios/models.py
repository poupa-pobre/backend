"""
Custom user model do projeto — RF-002.

Cada pessoa é um usuário independente, dono dos seus dados (privados por
padrão). O login é por **email** (não há username). O hash de senha vive no
campo `password` herdado de `AbstractBaseUser` (o `senha_hash` do modelo de
dados).
"""

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models

from apps.common.models import TimeStampedModel


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, nome, password, **extra):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        email = self.normalize_email(email)
        usuario = self.model(email=email, nome=nome, **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, email, nome="", password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, nome, password, **extra)

    def create_superuser(self, email, nome="", password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra.get("is_staff") is not True:
            raise ValueError("Superusuário precisa de is_staff=True.")
        if extra.get("is_superuser") is not True:
            raise ValueError("Superusuário precisa de is_superuser=True.")
        return self._create_user(email, nome, password, **extra)


class Usuario(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    nome = models.CharField("nome", max_length=100)
    email = models.EmailField("e-mail", max_length=255, unique=True)
    is_active = models.BooleanField("ativo", default=True)
    is_staff = models.BooleanField("equipe", default=False)

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nome"]

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} <{self.email}>"
