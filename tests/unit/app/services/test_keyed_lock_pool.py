import threading

from app.services.keyed_lock_pool import KeyedLockPool


def test_keyed_lock_pool_serializes_same_key_and_releases_entry():
    pool = KeyedLockPool()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_user():
        with pool.hold("video-1"):
            first_entered.set()
            release_first.wait(timeout=1)

    def second_user():
        with pool.hold("video-1"):
            second_entered.set()

    first = threading.Thread(target=first_user)
    second = threading.Thread(target=second_user)
    first.start()
    assert first_entered.wait(timeout=1)
    second.start()
    assert not second_entered.wait(timeout=0.05)

    release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert second_entered.is_set()
    assert pool._entries == {}
