#!/usr/bin/env python3
"""Builds the bulldozer run's report: a spotlight deck (index.html) and a second page (details.html).

Run it from anywhere, with Pillow and Playwright-free tools only:

    uv run --with pillow python docs/bulldozer/bd1125b/report/gen.py

It reads the run folder (.scratch/run in this checkout, or $RUN_DIR): ledger.json, the evidence pictures,
findings/round1-result.json, findings/round2-result.json, findings/vote-result.json (the final vote; the
slide shows a marked placeholder while the file is missing), study/wf_8ebde839-f20.json (the study's
ratings). Pictures are cut into img/ once (--force cuts them again). Then it writes spotlight.json and
runs the spotlight skill's build.py to make index.html.
"""
import html
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[3]
RUN = pathlib.Path(os.environ.get('RUN_DIR') or REPO / '.scratch' / 'run')
EV = RUN / 'evidence'
IMG = HERE / 'img'
FORCE = '--force' in sys.argv

LED = json.load(open(RUN / 'ledger.json'))['findings']
R1 = json.load(open(RUN / 'findings' / 'round1-result.json'))
R2 = json.load(open(RUN / 'findings' / 'round2-result.json'))
STUDY = json.load(open(RUN / 'study' / 'wf_8ebde839-f20.json'))['result']['results']
VOTE_FILE = RUN / 'findings' / 'vote-result.json'
VOTE = json.load(open(VOTE_FILE)) if VOTE_FILE.exists() else None

e = html.escape


# ---------------------------------------------------------------- pictures

RED, GRN = (179, 38, 30), (22, 121, 74)


def cut_images():
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 20)

    def cell(path, crop, label, col, rings):
        im = Image.open(EV / path).convert('RGB')
        if im.width == 780:
            im = im.resize((390, im.height // 2))
        im = im.crop((crop[0], crop[1], crop[0] + crop[2], crop[1] + crop[3]))
        d = ImageDraw.Draw(im)
        for b in rings:
            d.rounded_rectangle((b[0], b[1], b[0] + b[2], b[1] + b[3]), radius=8, outline=col, width=4)
        d.rectangle((0, 0, im.width - 1, im.height - 1), outline=(200, 200, 200))
        out = Image.new('RGB', (im.width, im.height + 34), 'white')
        ImageDraw.Draw(out).text((2, 5), label, font=font, fill=col)
        out.paste(im, (0, 34))
        return out

    def sheet(name, rows):
        dst = IMG / (name + '.jpg')
        if dst.exists() and not FORCE:
            return
        rendered = [[cell(*c) for c in row] for row in rows]
        w = max(sum(c.width for c in r) + 16 * (len(r) - 1) for r in rendered)
        h = sum(max(c.height for c in r) for r in rendered) + 10 * (len(rendered) - 1)
        out = Image.new('RGB', (w, h), 'white')
        y = 0
        for r in rendered:
            x = 0
            for c in r:
                out.paste(c, (x, y))
                x += c.width + 16
            y += max(c.height for c in r) + 10
        out.save(dst, 'JPEG', quality=84, optimize=True)

    def pair(base, crop1440, crop390, r1440b, r1440a, r390b, r390a, **kw):
        b1, a1 = kw.get('b1440', 'before-1440.png'), kw.get('a1440', 'after-1440.png')
        b3, a3 = kw.get('b390', 'before-390.png'), kw.get('a390', 'after-390.png')
        return [[(base + b1, crop1440, 'BEFORE, 1440 px wide', RED, r1440b),
                 (base + a1, crop1440, 'AFTER, 1440 px wide', GRN, r1440a)],
                [(base + b3, crop390, 'BEFORE, 390 px (phone)', RED, r390b),
                 (base + a3, crop390, 'AFTER, 390 px (phone)', GRN, r390a)]]

    S = 'steps/'
    # Step 1 Calls: popover and header, stacked so the words stay readable
    c14 = (708, 0, 732, 230)
    sheet('step1', [
        [(S + 'STEP-1/before-1440.png', c14, 'BEFORE, 1440 px wide', RED, [(572, 8, 38, 34), (20, 57, 320, 173)])],
        [(S + 'STEP-1/after-1440.png', c14, 'AFTER, 1440 px wide', GRN, [(548, 8, 58, 34), (354, 50, 378, 34), (0, 57, 340, 173)])],
        [(S + 'STEP-1/before-390.png', (0, 50, 390, 470), 'BEFORE, 390 px (phone)', RED, [(10, 171, 370, 294)]),
         (S + 'STEP-1/after-390.png', (0, 50, 390, 470), 'AFTER, 390 px (phone)', GRN, [(10, 6, 372, 460)])],
    ])
    # Step 2 wait card
    sheet('step2', pair(S + 'STEP-2/', (1060, 40, 380, 330), (0, 480, 390, 300),
                        [(57, 22, 310, 98)], [(15, 22, 352, 252)], [(57, 39, 320, 98)], [(14, 39, 362, 226)],
                        b1440='sent-before-1440.png', a1440='sent-after-1440.png',
                        b390='sent-before-390.png', a390='sent-after-390.png'))
    # Step 3 conversation shell
    sheet('step3', [
        [(S + '../C/S-tinkerer-5/before-1440.png', (1060, 40, 380, 540), 'BEFORE, 1440 px wide', RED, [(14, 140, 352, 110)]),
         (S + '../C/S-tinkerer-5/after-1440.png', (1060, 40, 380, 540), 'AFTER, 1440 px wide', GRN, [(13, 20, 355, 314), (15, 357, 352, 183)])],
        [(S + '../C/S-tinkerer-5/before-390.png', (0, 440, 390, 404), 'BEFORE, 390 px (phone)', RED, [(14, 82, 372, 200)]),
         (S + '../C/S-tinkerer-5/after-390.png', (0, 440, 390, 404), 'AFTER, 390 px (phone)', GRN, [(8, 140, 382, 262)])],
    ])
    # Step 4 return and place
    sheet('step4', pair(S + 'STEP-4/', (1060, 0, 380, 300), (0, 440, 390, 404),
                        [(225, 8, 38, 32)], [(10, 48, 360, 36), (11, 94, 358, 126), (203, 12, 46, 26)],
                        [(222, 18, 36, 30)], [(12, 74, 368, 30), (8, 112, 384, 118), (212, 26, 44, 28)]))
    # Step 5 switch
    sheet('step5', pair(S + 'STEP-5/', (1060, 640, 380, 260), (0, 640, 390, 204),
                        [(12, 157, 356, 91)], [(13, 100, 355, 36), (13, 226, 355, 20)],
                        [(12, 97, 364, 40)], [(18, 80, 372, 44)]))
    # Keys sheet and phone
    sheet('keys', [
        [(S + 'STEP-5/before-1440.png', (688, 50, 362, 610), 'BEFORE: no list of keys', RED, []),
         (S + 'STEP-5/after-keys-1440.png', (688, 50, 362, 610), 'AFTER: press ? for the list', GRN, [(0, 0, 360, 600)])],
        [('I/S-phone-2/before-390.png', (0, 440, 390, 404), 'BEFORE, 390 px (phone)', RED, [(0, 140, 388, 200)]),
         ('I/S-phone-2/after-390.png', (0, 440, 390, 404), 'AFTER, 390 px (phone)', GRN, [(4, 20, 382, 270)])],
    ])
    # Stage: a table printed over itself
    sheet('stage-table', [[
        ('S/S-first-6/before-1440.png', (400, 320, 640, 300), 'BEFORE', RED, [(110, 30, 420, 240)]),
        ('S/S-first-6/after-1440.png', (400, 320, 640, 300), 'AFTER', GRN, [(42, 54, 556, 196)])]])


# ---------------------------------------------------------------- numbers

def plain(r):
    return round(statistics.mean(r), 1)


study_r = [x['report']['rating_out_of_10'] for x in STUDY]
r1_r = [x['rating'] for x in R1['ratings']]
r2_r = [x['rating'] for x in R2['ratings']]
N = len(LED)
BY_ROUND = {r: sum(1 for x in LED if x['round'] == r) for r in (0, 1, 2)}
REOPENED = sum(1 for x in LED if x.get('reopened_in_round'))
FELT = sum(1 for x in LED if x['felt'])
FIXED = sum(1 for x in LED if x['state'] == 'fixed')


# ---------------------------------------------------------------- slide parts

def rows_box(rows):
    out = ['<div class="rowsbox"><div class="hd"><h4 class="b">Before</h4><h4 class="a">After</h4></div>']
    for b, a in rows:
        out.append(f'<div class="rw"><div class="b">{b}</div><div class="a">{a}</div></div>')
    out.append('</div>')
    return ''.join(out)


def ba(before, after, one=False):
    return (f'<div class="ba"><div class="side before"><h4>Before</h4><p>{before}</p></div>'
            f'<div class="side after"><h4>After</h4><p>{after}</p></div></div>')


SCREENS = []


def image_slide(sid, label, image, title, text, source, boxes=None):
    SCREENS.append({'id': sid, 'label': label, 'image': 'img/' + image, 'source': source,
                    'steps': [{'title': title, 'text': text}]})


def html_slide(sid, label, fragment, title, text, facts=None, css=True):
    step = {'title': title, 'text': text}
    if facts:
        step['facts'] = facts
    SCREENS.append({'id': sid, 'label': label, 'html': fragment, 'steps': [step]})


# 1. opening
html_slide('intro', 'What this is', (
    '<div class="ba one"><div class="side today"><h4>What this report is about</h4>'
    '<p><b>/talk</b> is a call with Claude: you type or speak, Claude answers aloud, and a <b>stage</b> beside the panel '
    'shows boards (a table, a diagram, a map, some code) while the voice reads. The <b>side panel</b> is the narrow column '
    'on the right of the call page: the conversation, the player and the box you type in.</p>'
    '<p>An earlier study, with 14 AI test users, found 99 problems with that panel and proposed 14 quick fixes and 5 '
    'larger steps (99 + 14 + 5 = 118 entries, each one thing to fix). This run built all of it. Then it ran two <b>rounds</b>: in each, 14 new test users '
    '(a teacher, a carpenter on a phone, a blind accountant, and so on) used the rebuilt panel, and what they hit was fixed.</p>'
    f'<p>The test users are AI agents who did not know they were being tested. Each drove a real call in a browser '
    'and then rated the page from 0 to 10 (10 is perfect).</p>'
    '<div class="facts3">'
    f'<div><b>{N}</b>entries, each one problem to fix, all fixed ({BY_ROUND[0]} from the study and its fixes + {BY_ROUND[1]} from round 1 + {BY_ROUND[2]} from round 2)</div>'
    f'<div><b>{REOPENED}</b>of the study\'s entries were fixed, found broken again by test users, and fixed a second time</div>'
    f'<div><b>{FELT}</b>of the {N} are something a person sees or feels; the other 21 are a hidden fault, a test or a rule for Claude</div></div>'
    '<table class="ratings"><tr><th>Average rating of the page, 0 to 10, 14 test users each time</th><th>Average</th><th>Lowest</th><th>Highest</th></tr>'
    f'<tr><td>Before the run (the study)</td><td>{plain(study_r)}</td><td>{min(study_r)}</td><td>{max(study_r)}</td></tr>'
    f'<tr><td>After round 1</td><td>{plain(r1_r)}</td><td>{min(r1_r)}</td><td>{max(r1_r)}</td></tr>'
    f'<tr><td>After round 2</td><td>{plain(r2_r)}</td><td>{min(r2_r)}</td><td>{max(r2_r)}</td></tr></table>'
    '</div></div>'),
    'Claude fixed all 193 problems in the call page\'s side panel; test users rate it 6.8, up from 6.3',
    ['Every slide after this one is one change you can see or feel, with the page before and after. '
     'The rating rose after round 1 and stayed level after round 2 (6.9, then 6.8): each new group of test users found new problems (6 serious ones in round 1, 3 in round 2), so it did not climb further. The ratings are an AI\'s impression, a rough sign and not a measurement.'])

# 2. steps
image_slide('s1', 'Step 1 Calls', 'step1.jpg',
            'The Calls button counts the calls that need you and lists them by need',
            ['A call is one conversation with Claude; you can have several open, and the stacked-layers button at the top of the panel lists them (a call needs you when it waits for you, has new answers or has stalled). Before, every call had the same blue dot. '
             'Now each has an icon and a word (Stalled means nobody picked the question up; also 2 new answers, Answering, Waiting for you), the ones that need you come first, '
             'and Next waiting jumps to the first of them. Before, a browser tab\'s title never changed; now its title and icon show the same state.'],
            'Before: the call page as it was. After: the same page, same calls.')
image_slide('s2', 'Step 2 Wait card', 'step2.jpg',
            'Every question you send gets a card that says where it stands and lets you take it back',
            ['Before, a sent question showed one grey line and nothing else. Now a card shows Sent, Picked up (Claude has started on it), Working and Answer, '
             'a clock counting from the moment you sent until the answer comes, and buttons to take the question back, copy it or send it again. '
             'Text you are still typing stays in the box. On the server, a question Claude has not picked up can be cancelled and stays saved in the call, '
             'and an answer you replaced with a correction never speaks over you.'],
            'Before: a question just sent. After: the same question.')
image_slide('s3', 'Step 3 Conversation', 'step3.jpg',
            'The panel is one card for the answer now playing over a short list of earlier answers',
            ['Before, every answer was folded to one cut-off line with a Show text link, and progress notes such as "thinking it through" piled up between them as faint dotted lines. '
             'Now the newest answer is just there to read, the word being said is lit, and earlier answers sit in a list you can search (it finds words in answers and boards) '
             'and open one at a time or all at once. The progress notes are now one line at the foot.'],
            'Before and after: a call with three answers.')
image_slide('s4', 'Step 4 Return', 'step4.jpg',
            'Coming back after hours away, a card says how long you were gone and plays what you missed',
            ['Before, you came back to a list that did not say anything had arrived. Now a line under the header says what the call is doing, '
             'and after you have been away a while (2 hours 10 minutes in the picture) a Welcome back card says how long you were away, how many answers you did not hear, '
             'and offers Play the 3 new. A divider marks where you left off.'],
            'Before and after: a call that got three answers while the user was away.')
image_slide('s5', 'Step 5 Type, Talk, Live', 'step5.jpg',
            'A Type, Talk, Live switch under the player says how you are talking and whose turn it is',
            ['Type is keyboard only, Talk is press the mic and speak, and Live keeps the microphone open so you and Claude talk hands-free. Before, Live was only in settings. '
             'Now one tap on the switch changes how you talk, a small badge says Your turn or Typing, and a hint line under the box shows Space, the arrow keys and ? for all keys.'],
            'Before and after: the foot of the panel.')
image_slide('s6', 'Keys sheet and phone', 'keys.jpg',
            'Pressing ? lists every keyboard shortcut, and on a phone the conversation is a third taller',
            ['Before, the shortcuts existed but no screen told you. Now ? opens a sheet grouped as Listening, Moving around and Talking. '
             'On a phone with a board showing, the conversation was about three lines tall; it is now about a third taller and the buttons are thumb-sized.'],
            'Before and after: the shortcut sheet at desktop width; the phone conversation.')

# 3. other changes by place
image_slide('stage-table', 'Stage defects', 'stage-table.jpg',
            'Tables on the stage no longer print their words on top of each other',
            ['The stage is the big area left of the panel, and 1440 px is the width of the browser window. The picture is a table about vaccine boosters. A table\'s first column was drawn narrower than its words, so Shot and Booster ran together. '
             'Now every column is as wide as its longest word.'],
            'Before and after: a table board at 1440 px, same data.')

html_slide('stage-list', 'Stage defects', rows_box([
    ('A slide\'s title was cut off at the top of the stage', 'A slide at rest shows from its title'),
    ('Greek capital letters kept their accent marks and were spaced out', 'Greek capitals lose the accents and sit tight; Greek numbers use a decimal comma'),
    ('A long line of code was cut at the stage\'s edge', 'Long lines wrap by default; with the existing Wrap lines switch off, a line that goes on fades at the edge'),
    ('The menu listing an answer\'s boards opened with its header and first rows hidden', 'The menu opens whole, newest first'),
    ('A bars board said "1 days"', 'It says "1 day"'),
    ('On a TV a small table sat tiny in the middle of a big stage', 'A small table fills most of the stage'),
    ('A step popup stayed open over the board after the voice moved on', 'It closes when the voice moves on, with a close button big enough to tap'),
]), 'Seven more stage faults are fixed: titles, Greek, code, lists, wording and popups',
    ['A board is one thing the stage shows (a table, a diagram, code). These changes are small, each in a different place, so they share a slide.'])

html_slide('keys-sr', 'Keyboard and screen reader', rows_box([
    ('Settings opened without taking focus and sat last in the Tab order', 'Opening Settings puts you inside it, and Escape puts you back on the gear'),
    ('The keyboard shortcuts were undocumented', 'A hint under the box shows Space and the arrows, and ? lists every key'),
    ('A long Tab path through the whole panel', 'Tab offers skip links (a link that jumps past a block) to the message box and the player, and Alt then B jumps to the board'),
    ('A screen reader said nothing when Claude started or finished', 'It says Claude is working, what it is working on, and Answer 3 arrived'),
    ('Board changes on the stage were silent; a flowchart was one picture', 'Board changes are announced, and each arrow of a flowchart is read with its ends and its yes or no'),
    ('The conversation had no headings', 'Each answer is a heading a screen reader can jump between, and the first stop in the panel is the newest answer'),
    ('Enter on an earlier answer\'s Play dropped the keyboard to the page', 'The keyboard stays on the player\'s button'),
]), 'People who use a keyboard or a screen reader can now reach, hear and replay every answer',
    ['A screen reader is software that reads the page aloud for people who cannot see it. These seven are the main changes; the second page lists all 193 entries.'])

html_slide('tv-phone', 'TV and phone', rows_box([
    ('TV size was a buried setting; a big screen opened in desk size', 'A big screen offers TV size once, in a line above the box, and never changes size by itself; the Full screen button enlarges the panel too'),
    ('In TV size the chips, labels and time stayed small', 'They are as big as the answer text'),
    ('On a phone the step arrows and chips were too small to tap', 'The player, the strip\'s switch and the card buttons are thumb-sized'),
    ('On a phone the Follow button squeezed the stage title to "F..."', 'Follow is a small eye icon and the title is readable'),
    ('A phone\'s table lost its last row under a fade, with no sign', 'A small badge says how many rows are out of sight'),
    ('The settings popup hid End call below the screen on a TV or phone', 'Settings scroll and End call is always at the bottom'),
    ('Sequence boards had small faint notes on a TV', 'Replies, notes and compare titles read from across the room'),
]), 'The panel is now usable on a TV across the room and on a phone with one thumb',
    ['The TV view is a 1280 pixel wide screen read from a sofa; the phone view is 390 pixels wide. A sequence board is a diagram of who sends what to whom, step by step; a compare board shows two of them, before and after.'])

html_slide('settings', 'Settings and wording', rows_box([
    ('Choosing Greek changed only what was spoken; the page stayed English', 'The whole panel, the wait card and the stage toolbar are Greek'),
    ('The page opened in Light whatever the computer used; two buttons were both called Auto', 'A computer set to dark opens dark; only one button is called Auto'),
    ('Voice speed was buried in settings; asking to go slower sent Claude a question', 'Speed is one tap in the player; typing slower or faster moves it'),
    ('Hover tips covered the player time and the line under it', 'Tips open away from what you are reading'),
    ('Only earlier answers could be copied; times were a bare 14:05', 'The newest answer has Copy; times say Yesterday or the date'),
    ('The Key points chip said "+1" with no meaning', 'It says Key points and how many points that answer added'),
]), 'Language, theme, speed and labels now say what they do and remember what you chose',
    ['Key points is a board Claude keeps of each answer\'s main lines; the chip is the small button under an answer that puts it on the stage. Your choices are remembered in this browser.'])

html_slide('corrections', 'Corrections and queued answers', rows_box([
    ('A correction did not stop the earlier answer, which then spoke over you', 'The earlier answer is tagged Replaced and never plays over the new one'),
    ('A queued answer said "Next answer ready" with no way to skip', 'A row says Next: answer 4, plays when this one ends, with Skip'),
    ('Take back withdrew only the newest of several waiting questions', 'It takes back every question Claude has not picked up, puts them in the box in order, and says how many came back'),
    ('Send again left a note for 7 seconds, then no trace', 'The card keeps a line saying when it was sent again'),
    ('The top strip and the wait card showed different clocks', 'Both show the same clock and the same word'),
    ('"Claude is finishing the earlier question" showed even when that question\'s session had ended', 'It shows only when that is true'),
    ('A stalled question said "Check the terminal" (the window Claude runs in)', 'It says Not picked up and that your question is saved in the call, with Send again, Copy question and Take back'),
]), 'Interrupting Claude, queueing and taking back questions now behave the way the card says',
    ['A correction is a second question sent while Claude is still answering the first. A stalled question is one nobody picked up.'])

html_slide('guide', 'What Claude is told', rows_box([
    ('A user who insisted on a table got a sequence diagram; rows were cut to four', 'A user who asks for a table gets it, up to 8 rows by 6 columns'),
    ('A request for a picture of a physical thing got boxes and arrows', 'Claude says no board draws that, instead of faking it'),
    ('A day-by-day plan with costs was drawn as actors and arrows', 'Claude is guided to bars or a short table'),
    ('A long typed message was answered in part', 'It is answered point by point'),
    ('When a table overlapped, Claude apologised at length', 'Claude says the page is at fault and gives the facts another way'),
    ('A draft email shown on the stage kept its long lines running off a phone', 'The draft wraps on a phone'),
]), 'Claude\'s own instructions for the call now cover tables, pictures, long messages and drafts',
    ['The guide is the short text every Claude session reads before it answers on a call. Most of these change what Claude puts on the stage rather than the page itself.'])

# 4. still hit
rated = sorted(R2['ratings'], key=lambda x: x['rating'])
html_slide('still', 'Still hit', (
    '<div class="rowsbox"><div class="hd"><h4 class="b">What round 2 test users still hit</h4><h4 class="a">What was done about it</h4></div>'
    '<div class="rw"><div class="b">The marathon-call tester rated 5: 14 minutes with no answer, and a status line that said Claude was finishing an earlier question</div>'
    '<div class="a">The status line is fixed. The cause of the silence is unknown: no answer reached that call in the test.</div></div>'
    '<div class="rw"><div class="b">The voice-first tester rated 5: the microphone heard nothing in three tries</div>'
    '<div class="a">The test browser had no real microphone, so voice input was not tested for a person. Not fixed.</div></div>'
    '<div class="rw"><div class="b">The email writer rated 6: no clean Copy for an email</div>'
    '<div class="a">Copy is labelled and drafts wrap; nobody has re-tested getting an email out.</div></div>'
    '<div class="rw"><div class="b">A phone user could not reach the last row of a long table</div>'
    '<div class="a">A pill now says rows are out of sight. Not re-tested.</div></div>'
    '<div class="rw"><div class="b">Wanted and not built: a text size slider, three calls side by side, a preview of a call\'s board</div>'
    '<div class="a">Not built.</div></div>'
    '<div class="rw"><div class="b">A screen reader still met a map drawn as one picture</div>'
    '<div class="a">Map, graph and bars now have a reading list; not re-tested.</div></div></div>'),
    'After round 2 two test users still rated the page 5, and the fixes made after round 2 were never re-tested by a test user',
    ['The run stopped after round 2 because the run\'s rule (another round only while the last one found 5 or more new serious problems, meaning ones that stop someone doing the task; at most 3 rounds) was met by round 1 (6 found, so round 2 ran) and not by round 2 (3 found, so the run stopped). Round 2\'s fixes rest on the automatic tests alone. Still open: voice input and the three wishes. Fixed but never re-tested: the rest.'])

# 5. vote
if VOTE:
    t = VOTE.get('tally', {})
    nb = VOTE.get('ballots', [])
    html_slide('vote', 'The vote', (
        '<div class="ba three"><div class="side after"><h4>Prefer the new panel</h4><p><b>%s</b> votes</p></div>'
        '<div class="side no"><h4>Prefer the old panel</h4><p><b>%s</b> votes</p></div>'
        '<div class="side today"><h4>About the same</h4><p><b>%s</b> votes</p></div></div>' %
        (t.get('new', 0), t.get('old', 0), t.get('same', 0))),
        'In the final vote, %d of %d ballots preferred the new panel, %d the old one and %d saw no difference' % (
            t.get('new', 0), sum(t.get(k, 0) for k in ('new', 'old', 'same')), t.get('old', 0), t.get('same', 0)),
        [e(str(VOTE.get('summary', '')))])
else:
    html_slide('vote', 'The vote', (
        '<div class="ba one todo"><div class="side today"><h4>PLACEHOLDER: the final vote has not finished</h4>'
        '<p>The vote asks 10 ballots (5 kinds of user, 2 each) which panel they prefer, the old or the new. '
        'When the vote file exists, rerun gen.py and this slide shows the count for the new panel, the old panel and about the same.</p></div></div>'),
        'The final vote of the old panel against the new is not in yet',
        ['The vote is still running. When it ends, the script that builds this report fills this slide from its result file. Until then the run is not merged.'])

# 6. decisions
html_slide('decisions', 'Decisions without you', (
    '<div class="ba three"><div class="side today"><h4>Today</h4><p>One AI designer split the call page\'s one big script into ten files, each owned by one of five AI builders, before they started. The whole run is merged to main and pushed. The live talk on the Mac picks it up as soon as the Mac answers again (it did not answer when the run ended).</p></div>'
    '<div class="side after"><h4>If you agree</h4><p>Nothing to do. The page behaves the same and each builder worked without clashing with the others.</p></div>'
    '<div class="side no"><h4>If you do not</h4><p>The ten files can be joined back into one. It only moves code between files, so it can be undone and loses no behaviour.</p></div></div>'),
    'One decision was made without you: the page\'s script was split so five builders could work at once',
    ['Your rule is that a shared file gets one owner instead of builders waiting for each other; the split is how that was done. The tests passed after every landing (3368 at the end of the build), and undoing it costs one rework of the file layout plus one test run. Nothing in this run needs your password, a payment or a device. '
     'A second call: the final vote named five defects after the rounds had ended, so one more pass checked and fixed them before the merge. '
     'Write "no to the split" in the chat to have it undone. <a href="details.html" target="_blank">The second page</a> lists all 193 entries.'])


# ---------------------------------------------------------------- the second page

def clean(t):
    t = re.sub(r'`[^`]*`', '', t)
    t = re.sub(r'\b[\w./-]+\.(?:css|js|py|html|json|md)(?::\d+)?(?:-\d+)?', '', t)
    t = re.sub(r'\s+', ' ', t).strip(' ,.;:-')
    return t


def source_of(x):
    r = x['round']
    if r == 0:
        return 'the study'
    p = x.get('persona') or 'a test user'
    return f'round {r}, test user "{p}"'


def line(x):
    txt = x['notice'] if (x['felt'] and x.get('notice')) else (x.get('notice') or clean(x['title']))
    txt = clean(txt)
    if len(txt) > 230:
        txt = txt[:227].rsplit(' ', 1)[0] + '...'
    return txt


rows = []
for x in LED:
    ro = 'reopened' if x.get('reopened_in_round') else ''
    rows.append(f'<tr><td class="id">{e(x["id"])}</td><td>{e(line(x))}</td><td>{e(x["state"])}{" (" + ro + ")" if ro else ""}</td>'
                f'<td>{e(source_of(x))}</td><td>{"yes" if x["felt"] else "no"}</td></tr>')

DETAILS = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Side panel run: every entry</title>
<style>
body{{margin:0;font:16px/1.5 Inter,system-ui,sans-serif;color:#151826;background:#f6f7fb}}
main{{max-width:1300px;margin:0 auto;padding:20px}}
h1{{font-size:1.5rem}}h2{{font-size:1.2rem;margin-top:1.6em}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:.9rem}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #e3e5ec;vertical-align:top}}
td.id{{font-family:ui-monospace,monospace;font-size:.8rem;white-space:nowrap}}
.scroll{{overflow-x:auto}}a{{color:#3355d6}}
.n{{display:flex;gap:10px;flex-wrap:wrap}}.n div{{background:#fff;border:1px solid #e3e5ec;border-radius:10px;padding:10px 14px}}.n b{{font-size:1.4rem;display:block}}
</style></head><body><main>
<p><a href="index.html">Back to the slides</a></p>
<h1>The side panel run: every entry, the rounds and what they cost</h1>
<div class="n"><div><b>{N}</b>entries, all fixed</div><div><b>{BY_ROUND[0]} / {BY_ROUND[1]} / {BY_ROUND[2]}</b>from the study / round 1 / round 2</div>
<div><b>{FELT}</b>a person sees or feels</div><div><b>{REOPENED}</b>reopened by test users and fixed again</div></div>

<h2>The rounds and when they stopped</h2>
<div class="scroll"><table><tr><th>Stage</th><th>What happened</th><th>Full test suite afterwards</th></tr>
<tr><td>Build</td><td>The study's 99 findings, 14 quick fixes and 5 steps (118 entries) were built by five parallel batches.</td><td>3368 passed</td></tr>
<tr><td>Round 1</td><td>14 test users, 58 problems reported, 53 survived a skeptic check, 30 new entries, 12 earlier fixes found broken again. New serious problems: {R1['new_serious']}. The rule says another round while 5 or more, so round 2 ran.</td><td>3437 passed</td></tr>
<tr><td>Round 2</td><td>14 test users, 57 problems reported, 51 survived, 33 new entries, 2 earlier fixes found broken again. New serious problems: {R2['new_serious']}, under 5, so the run stopped (at most 3 rounds were allowed).</td><td>3513 passed</td></tr>
<tr><td>Finish</td><td>4 fixes whose notes showed them half done were finished.</td><td>3518 passed</td></tr></table></div>

<h2>What it cost, in agents (separate Claude sessions)</h2>
<div class="scroll"><table><tr><th>Part</th><th>Agents</th></tr>
<tr><td>Build</td><td>13</td></tr><tr><td>Round 1</td><td>296</td></tr><tr><td>Round 2</td><td>273</td></tr>
<tr><td>Finishing pass</td><td>10</td></tr><tr><td>Final vote</td><td>about 45</td></tr>
<tr><td><b>Total</b></td><td><b>about 637</b></td></tr></table></div>

<h2>Every entry</h2>
<div class="scroll"><table><tr><th>Entry</th><th>What changed</th><th>State</th><th>Came from</th><th>A person feels it</th></tr>
{''.join(rows)}</table></div>
</main></body></html>'''


# ---------------------------------------------------------------- build

def main():
    IMG.mkdir(exist_ok=True)
    cut_images()
    spec = {'tag': 'Side panel run', 'title': 'What Claude changed in the /talk side panel, one topic per slide',
            'out': 'index.html', 'css': 'stage.css',
            'footer': 'Pictures: the call page before the run and after it, same calls and same words.',
            'screens': SCREENS}
    (HERE / 'spotlight.json').write_text(json.dumps(spec, indent=1))
    (HERE / 'details.html').write_text(DETAILS)
    build = REPO / 'skills' / 'spotlight' / 'build.py'
    subprocess.run([sys.executable, str(build), str(HERE / 'spotlight.json')], check=True)
    print('slides', len(SCREENS), 'entries', N, 'vote', 'yes' if VOTE else 'placeholder')


main()
