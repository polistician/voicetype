# test_autogen.py
from autogen import generate


def test_empty_body():
    r = generate("")
    assert r["name"] == "Untitled"
    assert r["description"] == ""
    assert r["tags"] == ""


def test_short_single_line():
    r = generate("deploy v3 to production")
    assert r["name"] == "deploy v3 to production"
    # Tags come from the body
    assert "deploy" in r["tags"] or "production" in r["tags"]


def test_strips_shell_prompt():
    r = generate("❯ git push origin main\n❯ ssh server")
    assert not r["name"].startswith("❯")
    assert "git" in r["name"] or "push" in r["name"]


def test_long_first_line_truncates_to_words():
    body = "this is a really very long description of some thing that someone would definitely never name a snippet as all of this text"
    r = generate(body)
    # Name capped at 80 chars, typically first ~6 words
    assert len(r["name"]) <= 80
    assert r["name"].startswith("this is a")


def test_description_from_sentences():
    body = "Deploy the crypto app to production. This pushes v3 and restarts the API. It also syncs research output."
    r = generate(body)
    assert "Deploy" in r["description"] or "production" in r["description"]
    assert len(r["description"]) <= 200


def test_tags_are_meaningful():
    body = "deploy the crypto app deploy production crypto deployment"
    r = generate(body)
    # Stopwords filtered, meaningful words remain
    assert "the" not in r["tags"].split(",")
    assert len(r["tags"].split(",")) <= 3


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
