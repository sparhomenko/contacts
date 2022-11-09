import yaml
from telethon import functions
from telethon.sync import TelegramClient


class Photo:
    def __init__(self) -> None:
        with open("secrets.yaml", "r") as file:
            config = yaml.safe_load(file)
        self._client = TelegramClient("Contacts", config["telegram"]["api_id"], config["telegram"]["api_hash"])
        self._client.start()
        self._client.connect()
        self._users = {}
        for user in self._client(functions.contacts.GetContactsRequest(0)).users:
            if user.photo:
                self._users[f"+{user.phone}"] = user

    def lookup(self, cache, phone):
        if user := self._users.get(phone):
            for photo in self._client.iter_profile_photos(user):
                if (key := str(photo.id)) not in cache:
                    cache[key] = True
                    yield self._client.download_media(photo, file=bytes)
