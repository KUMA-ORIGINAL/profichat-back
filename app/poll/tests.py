import uuid

from django.core.cache import cache
from django.test import TestCase, override_settings

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=LOCMEM)
class CorporatePollTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b = str(uuid.uuid4()), str(uuid.uuid4())

    def post(self, path, **data):
        return self.client.post(f'/api/corporate-poll/{path}', data, content_type='application/json')

    def test_page_renders(self):
        self.assertContains(self.client.get('/corporate/'), 'корпоратив')

    def test_place_vote_wish_flow(self):
        r = self.post('places/', token=self.a, name='Аня', title='Боулинг')
        self.assertEqual(r.status_code, 201)
        pid = r.json()['id']
        self.assertEqual(self.post('votes/', token=self.b, name='Боря', placeId=pid, on=True).status_code, 204)
        self.assertEqual(self.post('wish/', token=self.b, name='Боря', wish='до 2000').status_code, 204)

        state = self.client.get('/api/corporate-poll/').json()
        self.assertEqual(len(state['places'][0]['voters']), 2)
        self.assertEqual({p['name'] for p in state['people']}, {'Аня', 'Боря'})

        self.post('votes/', token=self.b, name='Боря', placeId=pid, on=False)
        self.assertEqual(len(self.client.get('/api/corporate-poll/').json()['places'][0]['voters']), 1)

    def test_only_author_can_delete(self):
        pid = self.post('places/', token=self.a, name='Аня', title='Баня').json()['id']
        url = f'/api/corporate-poll/places/{pid}/'
        self.assertEqual(self.client.delete(f'{url}?token={self.b}&name=Боря').status_code, 404)
        self.assertEqual(self.client.delete(f'{url}?token={self.a}&name=Аня').status_code, 204)
