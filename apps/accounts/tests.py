from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Profile

User = get_user_model()
PW = 'Str0ng-Pass-993'


def make_user(username='alice', email='alice@example.com', **kw):
    return User.objects.create_user(username=username, email=email, password=PW, first_name='Alice', **kw)


class RegistrationTests(TestCase):
    data = {'username': 'bob', 'first_name': 'Bob', 'last_name': 'K', 'email': 'bob@example.com',
            'phone': '9876543210', 'password1': PW, 'password2': PW}

    def test_register_creates_user_profile_and_logs_in(self):
        r = self.client.post(reverse('accounts:register'), self.data)
        self.assertRedirects(r, reverse('core:home'))
        u = User.objects.get(username='bob')
        self.assertEqual(u.profile.role, Profile.ROLE_USER)
        self.assertEqual(u.profile.phone, '9876543210')
        self.assertEqual(int(self.client.session['_auth_user_id']), u.pk)

    def test_cannot_register_as_admin(self):
        self.client.post(reverse('accounts:register'), {**self.data, 'role': 'admin'})
        self.assertEqual(User.objects.get(username='bob').profile.role, Profile.ROLE_USER)

    def test_duplicate_email_case_insensitive_rejected(self):
        make_user(email='bob@example.com', username='other')
        r = self.client.post(reverse('accounts:register'), {**self.data, 'email': 'BOB@example.com'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username='bob').exists())

    def test_weak_password_and_bad_phone_rejected(self):
        r = self.client.post(reverse('accounts:register'),
                             {**self.data, 'password1': '1234', 'password2': '1234', 'phone': 'abc'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username='bob').exists())


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_login_success_and_failure(self):
        bad = self.client.post(reverse('accounts:login'), {'username': 'alice', 'password': 'nope'})
        self.assertEqual(bad.status_code, 200)
        ok = self.client.post(reverse('accounts:login'), {'username': 'alice', 'password': PW})
        self.assertRedirects(ok, reverse('core:home'))

    def test_login_next_redirect_and_open_redirect_blocked(self):
        url = reverse('accounts:login')
        r = self.client.post(url + '?next=/accounts/profile/', {'username': 'alice', 'password': PW})
        self.assertRedirects(r, reverse('accounts:profile'))
        self.client.logout()
        r = self.client.post(url, {'username': 'alice', 'password': PW, 'next': 'https://evil.example/'})
        self.assertRedirects(r, reverse('core:home'))

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('accounts:logout')).status_code, 405)
        self.client.post(reverse('accounts:logout'))
        self.assertNotIn('_auth_user_id', self.client.session)


class ProfileTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user('carol', 'carol@example.com')

    def test_profile_requires_login(self):
        r = self.client.get(reverse('accounts:profile'))
        self.assertRedirects(r, f"{reverse('accounts:login')}?next={reverse('accounts:profile')}")

    def test_update_own_profile_only(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse('accounts:profile'), {
            'first_name': 'Alicia', 'last_name': '', 'email': 'alicia@example.com', 'phone': '+919876543210'})
        self.assertRedirects(r, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Alicia')
        self.assertEqual(self.user.profile.phone, '+919876543210')
        self.assertEqual(self.other.first_name, 'Alice')

    def test_profile_email_must_be_unique(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse('accounts:profile'), {
            'first_name': 'A', 'email': 'carol@example.com', 'phone': ''})
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'alice@example.com')

    def test_password_change(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse('accounts:password_change'), {
            'old_password': PW, 'new_password1': 'An0ther-Pass-771', 'new_password2': 'An0ther-Pass-771'})
        self.assertRedirects(r, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('An0ther-Pass-771'))


class RoleTests(TestCase):
    def test_dashboard_anonymous_redirected_user_forbidden_admin_ok(self):
        url = reverse('dashboard:index')
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(url).status_code, 403)
        admin = make_user('boss', 'boss@example.com')
        admin.profile.role = Profile.ROLE_ADMIN
        admin.profile.save()
        self.client.force_login(admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_superuser_gets_admin_role(self):
        su = User.objects.create_superuser('root', 'root@example.com', PW)
        self.assertEqual(su.profile.role, Profile.ROLE_ADMIN)

    def test_navbar_shows_dashboard_only_for_admin(self):
        self.client.force_login(make_user())
        self.assertNotContains(self.client.get(reverse('core:home')), reverse('dashboard:index'))


class APITests(TestCase):
    reg = {'username': 'dave', 'password': PW, 'first_name': 'Dave', 'email': 'dave@example.com', 'phone': '9876543210'}

    def test_register_login_profile_flow(self):
        r = self.client.post(reverse('api-register'), self.reg, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['user']['role'], 'user')
        self.assertNotIn('password', r.json()['user'])
        r = self.client.post(reverse('api-login'), {'username': 'dave', 'password': PW}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        auth = {'HTTP_AUTHORIZATION': f"Token {r.json()['token']}"}
        self.assertEqual(self.client.get(reverse('api-profile'), **auth).json()['username'], 'dave')
        r = self.client.patch(reverse('api-profile'), {'first_name': 'David'}, content_type='application/json', **auth)
        self.assertEqual(r.json()['first_name'], 'David')

    def test_register_cannot_set_role_and_validates(self):
        r = self.client.post(reverse('api-register'), {**self.reg, 'role': 'admin'}, content_type='application/json')
        self.assertEqual(User.objects.get(username='dave').profile.role, 'user')
        r = self.client.post(reverse('api-register'), {**self.reg, 'username': 'x', 'password': '123'}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post(reverse('api-register'), {**self.reg, 'username': 'y'}, content_type='application/json')
        self.assertEqual(r.status_code, 400)  # duplicate email

    def test_bad_login_and_unauthenticated_access(self):
        make_user('eve', 'eve@example.com')
        r = self.client.post(reverse('api-login'), {'username': 'eve', 'password': 'wrong'}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get(reverse('api-profile')).status_code, 401)

    def test_api_logout_revokes_token(self):
        r = self.client.post(reverse('api-register'), self.reg, content_type='application/json')
        auth = {'HTTP_AUTHORIZATION': f"Token {r.json()['token']}"}
        self.assertEqual(self.client.post(reverse('api-logout'), **auth).status_code, 204)
        self.assertEqual(self.client.get(reverse('api-profile'), **auth).status_code, 401)


class IsAdminRolePermissionTests(TestCase):
    def test_permission_class(self):
        from rest_framework.test import APIRequestFactory
        from .permissions import IsAdminRole
        req = APIRequestFactory().get('/')
        req.user = make_user()
        self.assertFalse(IsAdminRole().has_permission(req, None))
        req.user.profile.role = Profile.ROLE_ADMIN
        self.assertTrue(IsAdminRole().has_permission(req, None))


class BackfillTests(TestCase):
    def test_profile_created_for_any_user(self):
        self.assertTrue(Profile.objects.filter(user=make_user()).exists())
