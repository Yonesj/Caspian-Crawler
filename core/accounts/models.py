from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Project user model.

    Defining it now keeps ``AUTH_USER_MODEL`` stable: swapping the user model
    after the first migration is a painful, manual migration.
    """

    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'

    def __str__(self):
        return self.get_username()
