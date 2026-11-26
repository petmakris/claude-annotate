"""The work rule: which sessions must never leave their machine with their words.

One function decides (`is_work`); env imports it from here, fleet never imports env. A work session's journal
entry is masked on the writing machine (`mask_fields`) before it is written, and the hub refuses a work entry that
still carries a forbidden field (`work_refusal`). Contract: `fleet/docs/session-index.md`, section 7.
Stdlib only, Python 3.9+, no fleet imports.
"""
import json
import os
import shlex

FORBIDDEN = ("first_prompt", "last_prompt", "last_answer", "cwd", "account", "description", "rc_name")
PROMPT_NAME_SOURCES = ("ai", "registry", "prompt")


class Rules:
    """The rules of `$FLEET_HOME/work.json`. `fail_closed` is set when the file is missing or broken on a machine
    with the env repo: then every session counts as work."""

    def __init__(self, accounts=None, profile_paths=None, own_profiles=None, home=None, fail_closed=False):
        self.accounts = list(accounts or [])
        self.profile_paths = [os.path.normpath(os.path.expanduser(p)) for p in profile_paths or ()]
        self.own_profiles = os.path.expanduser(own_profiles) if own_profiles else None
        self.home = os.path.normpath(home or os.path.expanduser("~"))
        self.fail_closed = fail_closed

    def __repr__(self):
        return "Rules(accounts=%r, profile_paths=%r, own_profiles=%r, fail_closed=%r)" % (
            self.accounts, self.profile_paths, self.own_profiles, self.fail_closed)


def _fleet_home():
    return os.environ.get("FLEET_HOME") or os.path.join(os.path.expanduser("~"), ".claude", "fleet")


def _valid(conf):
    if not isinstance(conf, dict):
        return False
    acc, paths, own = conf.get("accounts"), conf.get("profile_paths"), conf.get("own_profiles")
    return (isinstance(acc, list) and acc and all(isinstance(a, str) and a for a in acc)
            and isinstance(paths, list) and all(isinstance(p, str) and p for p in paths)
            and (own is None or isinstance(own, str)))


def load_rules(fleet_home=None, home=None):
    """The rules on this machine. A missing or broken work.json fails closed when `~/projects/env` exists (a
    machine set up for work data), and open when it does not (a machine without the env repo)."""
    home = os.path.normpath(home or os.path.expanduser("~"))
    path = os.path.join(fleet_home or _fleet_home(), "work.json")
    try:
        with open(path) as f:
            conf = json.load(f)
    except (OSError, ValueError):
        conf = None
    if not _valid(conf):
        return Rules(home=home, fail_closed=os.path.isdir(os.path.join(home, "projects", "env")))
    return Rules(conf["accounts"], conf["profile_paths"], conf.get("own_profiles"), home=home)


def account_of(config_dir, rules):
    """The listed account a Claude config folder belongs to, or None for a folder no listed account has."""
    if not rules.accounts or not config_dir:
        return None
    cfg = os.path.normpath(os.path.expanduser(config_dir))
    if cfg == os.path.join(rules.home, ".claude"):
        return rules.accounts[0]
    base = os.path.basename(cfg)
    if os.path.dirname(cfg) == rules.home and base.startswith(".claude-") and base[len(".claude-"):] in rules.accounts[1:]:
        return base[len(".claude-"):]
    return None


def config_dir_of(transcript):
    """The Claude config folder a transcript sits in (the part before `/projects/`), or None."""
    if transcript and "/projects/" in transcript:
        return os.path.normpath(transcript[:transcript.index("/projects/")])
    return None


def _launch_profile(folder):
    """The `profile <name>` of the nearest .claude-launch at or above folder, or None."""
    d = os.path.normpath(folder)
    while True:
        f = os.path.join(d, ".claude-launch")
        if os.path.isfile(f):
            try:
                with open(f) as fh:
                    for line in fh:
                        try:
                            toks = shlex.split(line, comments=True)
                        except ValueError:
                            continue
                        if len(toks) >= 2 and toks[0] == "profile":
                            return toks[1]
            except OSError:
                pass
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _work_folder(folder, rules):
    f = os.path.normpath(os.path.expanduser(folder))
    for p in rules.profile_paths:
        if f == p or f.startswith(p.rstrip("/") + "/"):
            return True
    name = _launch_profile(f)
    if not name:
        return False
    own = rules.own_profiles and os.path.isfile(os.path.join(rules.own_profiles, name + ".args"))
    if own:
        return False
    return any(os.path.isfile(os.path.join(p, "claude", "profiles", name + ".args")) for p in rules.profile_paths)


def is_work(folder, transcript, rules):
    """True for a work session: a transcript under a config folder no listed account has, a folder under a path
    profile, or a folder whose launch profile only a path profile holds. A rule that raises says work."""
    try:
        if rules.fail_closed:
            return True
        if not rules.accounts:
            return False  # no work.json and no env repo: nothing is work
        cfg = config_dir_of(transcript)
        if cfg is not None and account_of(cfg, rules) is None:
            return True
        return bool(folder) and _work_folder(folder, rules)
    except Exception:  # noqa: B902 - a session that cannot be judged never leaves its machine whole
        return True


def mask_fields(fields):
    """The fields with every word of a work session removed: the forbidden fields, a prompt-derived name (or a
    name of no stated source) and the tmux name. `work` stays true."""
    out = {k: v for k, v in (fields or {}).items() if k not in FORBIDDEN}
    if "name" in out and out.get("name_source") not in NAME_SOURCES_NOT_FROM_PROMPT:
        out.pop("name", None)
        out.pop("name_source", None)
    elif "name_source" in out and "name" not in out and out["name_source"] in PROMPT_NAME_SOURCES:
        out.pop("name_source")
    obs = out.get("observed")
    if isinstance(obs, dict) and "tmux" in obs:
        obs = dict(obs)
        obs.pop("tmux")
        out["observed"] = obs
    out["work"] = True
    return out


NAME_SOURCES_NOT_FROM_PROMPT = ("manual", "custom", "topic", "job", "agent", "fleet")


def work_refusal(fields):
    """Why a work entry may not be stored (it carries a field `mask_fields` removes), or None."""
    fields = fields or {}
    for k in FORBIDDEN:
        if k in fields:
            return "a work entry carries %s" % k
    if "name" in fields and fields.get("name_source") not in NAME_SOURCES_NOT_FROM_PROMPT:
        return "a work entry carries a name taken from a prompt"
    obs = fields.get("observed")
    if isinstance(obs, dict) and obs.get("tmux") is not None:
        return "a work entry carries a tmux name"
    return None
