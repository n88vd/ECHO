from app.pipeline.places import dbscan, haversine_m, label_home_work, max_speed_kmh
from app.pipeline.text_qa import assess, has_remember_trigger, redact
from app.pipeline.understand import grounding_score


def test_assess_rejects_junk():
    assert assess("", 2, 0.9, 30, False).score == 0
    assert assess("hmm haan okay", 2, 0.9, 30, False).reason == "fillers_only"
    assert assess("Thank you for watching, please subscribe", 3, 0.9, 30, False).score < 0.3
    assert assess("the the the the the the the the the the", 3, 0.9, 30, False).score < 0.3


def test_assess_accepts_multilingual():
    assert assess("मैंने अपना पासपोर्ट नीले बैग में रखा है", 4, 0.95, 30, False).score >= 0.6
    assert assess("I will send the report to Rahul by Friday", 3, 0.9, 25, False).score >= 0.6
    assert assess("நாளை டாக்டரை பார்க்க வேண்டும்", 3, 0.9, 25, False).score >= 0.6


def test_redaction():
    t, changed = redact("my otp is 482913 and card 4111 1111 1111 1111, password is hunter2")
    assert changed and "482913" not in t and "4111" not in t and "hunter2" not in t
    assert redact("call me at 5 pm")[1] is False


def test_remember_trigger():
    assert has_remember_trigger("Echo, remember this: parking is on level 3")
    assert has_remember_trigger("Echo, yaad rakhna, kal meeting hai")
    assert has_remember_trigger("एको, इसे याद रखना")
    assert has_remember_trigger("इको, याद रखना, मैंने प्रिया को बोला है")
    assert not has_remember_trigger("I remember this place")


def test_grounding():
    ev = ["Rahul, I promise I will send you the project report by Friday evening."]
    assert grounding_score("You promised Rahul you would send the project report by Friday.", ev, ["Rahul"]) > 0.6
    assert grounding_score("You agreed to buy a car from Sanjay in Goa.", ev, ["Sanjay"]) < 0.3


def test_places():
    home = (12.9716, 77.5946)
    pts = [home, (12.9717, 77.5947), (12.9715, 77.5945), (13.0827, 80.2707)]
    labels = dbscan(pts, eps_m=75, min_pts=3)
    assert labels[:3] == [0, 0, 0] and labels[3] == -1
    assert 280_000 < haversine_m(home, (13.0827, 80.2707)) < 300_000
    assert max_speed_kmh([(0, 12.97, 77.59), (60, 12.98, 77.60)]) > 25
    assert label_home_work([(23, 1, True)] * 6) == "Home"
    assert label_home_work([(11, 2, True)] * 6) == "Work"
