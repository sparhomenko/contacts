import os
import shelve
from datetime import datetime
from typing import Final

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from libgravatar import Gravatar
from more_itertools import only
from phonenumbers import PhoneNumberFormat, format_number
from phonenumbers import parse as parse_number
from requests import get
from waiting import wait

from Contacts import (
    CNContactEmailAddressesKey,
    CNContactFormatter,
    CNContactFormatterStyleFullName,
    CNContactImageDataAvailableKey,
    CNContactImageDataKey,
    CNContactNoteKey,
    CNContactPhoneNumbersKey,
    CNContactStore,
    CNContactThumbnailImageDataKey,
    CNEntityTypeContacts,
    CNLabeledValue,
    CNSaveRequest,
)
from contacts.photo import offer
from contacts.telegram import Photo

_KEYS: Final = [
    CNContactFormatter.descriptorForRequiredKeysForStyle_(CNContactFormatterStyleFullName),
    CNContactPhoneNumbersKey,
    CNContactImageDataAvailableKey,
    CNContactThumbnailImageDataKey,
    CNContactImageDataKey,
    CNContactNoteKey,
    CNContactEmailAddressesKey,
]
store = CNContactStore.alloc().init()
done = False

SCOPES = ["https://www.googleapis.com/auth/contacts"]

credentials = None
if os.path.exists("token.json"):
    credentials = Credentials.from_authorized_user_file("token.json", SCOPES)
if not credentials or not credentials.valid:
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        credentials = flow.run_local_server(port=0)
    with open("token.json", "w") as token:
        token.write(credentials.to_json())

service = build("people", "v1", credentials=credentials)


def _completion_handler(granted: bool, error):
    if not granted:
        raise ValueError(error)
    global done
    done = True


store.requestAccessForEntityType_completionHandler_(CNEntityTypeContacts, _completion_handler)
wait(lambda: done)

contacts, _ = store.unifiedContactsMatchingPredicate_keysToFetch_error_(None, _KEYS, None)
save = CNSaveRequest.alloc().init()
formatter = CNContactFormatter.alloc().init()

google_cache = shelve.open("google.cache")
image_cache = shelve.open("image.cache")


def lookup_google_photo(id_type, id_value):
    photo = None
    account_id = google_cache.get(id_value)
    if account_id:
        if isinstance(account_id, str):
            google_cache[id_value] = (account_id, datetime.now())
            return None
        else:
            account_id, date = account_id
        if account_id != "N/A" and (datetime.now() - date).days > 1:
            try:
                photo = only(service.people().get(resourceName=f"people/{account_id}", personFields="photos").execute()["photos"])
            except HttpError as err:
                if err.status_code == 404:
                    del google_cache[id_value]
                    account_id = None
    if not account_id:
        contact = service.people().createContact(body={id_type: [{"value": id_value}]}).execute()
        account_id = "N/A"
        try:
            for contact_photo in contact["photos"]:
                source = contact_photo["metadata"]["source"]
                if source["type"] == "PROFILE":
                    account_id = source["id"]
                    photo = contact_photo
                    break
        finally:
            service.people().deleteContact(resourceName=contact["resourceName"]).execute()
    google_cache[id_value] = (account_id, datetime.now())
    if photo and (url := photo["url"].replace("=s100", "=s0")) not in image_cache:
        image_cache[url] = True
        response = get(url)
        response.raise_for_status()
        if response.headers["Content-Type"] != "image/png":  # Only default Google profile photos use PNG
            return response.content


def lookup_gravatar_photo(email):
    if (url := Gravatar(email).get_image(default="404", rating="x") + "&size=2048") not in image_cache:
        image_cache[url] = True
        response = get(url)
        if response.status_code != 404:
            response.raise_for_status()
            return response.content


telegram_photo = Photo()


for contact in contacts:
    name = f"{formatter.stringFromContact_(contact)}"
    mutable = contact.mutableCopy()
    changed = False

    photo_data = contact.imageData() or contact.thumbnailImageData()  # Thumbnail is sometimes available even when image is not (bug?)
    for email in contact.emailAddresses():
        if new_photo_data := lookup_google_photo("emailAddresses", email.value()):
            if offer(name, email.value(), (photo_data, new_photo_data)):
                photo_data = new_photo_data
                mutable.setImageData_(new_photo_data)
                changed = True
        if new_photo_data := lookup_gravatar_photo(email.value()):
            if offer(name, email.value(), (photo_data, new_photo_data)):
                photo_data = new_photo_data
                mutable.setImageData_(new_photo_data)
                changed = True
    phones = []
    phones_changed = False
    for phone in contact.phoneNumbers():
        number = phone.value()
        original = phone.value().stringValue()
        parsed = parse_number(original, "NL")
        formatted = format_number(parsed, PhoneNumberFormat.INTERNATIONAL)
        if formatted.startswith("+31 6 "):  # Noone really formats Dutch mobile numbers like this, reformat
            formatted = f"{formatted[:-8]}{formatted[-8:-6]} {formatted[-6:-4]} {formatted[-4:-2]} {formatted[-2:]}"
        if original != formatted:
            print(f"{original} → {formatted}")
            phone = CNLabeledValue.labeledValueWithLabel_value_(phone.label(), number.initWithStringValue_(formatted))
            phones_changed = True
        # TODO: extract to a function
        raw = format_number(parsed, PhoneNumberFormat.E164)
        if new_photo_data := lookup_google_photo("phoneNumbers", raw):
            if offer(name, raw, (photo_data, new_photo_data)):
                photo_data = new_photo_data
                mutable.setImageData_(new_photo_data)
                changed = True
        for new_photo_data in telegram_photo.lookup(image_cache, raw):
            if offer(name, raw, (photo_data, new_photo_data)):
                photo_data = new_photo_data
                mutable.setImageData_(new_photo_data)
                changed = True
        phones.append(phone)
    if phones_changed:
        mutable.setPhoneNumbers_(phones)
        changed = True
    if changed:
        save.updateContact_(mutable)
        success, _ = store.executeSaveRequest_error_(save, None)
        assert success
        save = CNSaveRequest.alloc().init()
    # TODO: update phonetic name to help Siri?
success, _ = store.executeSaveRequest_error_(save, None)
assert success
