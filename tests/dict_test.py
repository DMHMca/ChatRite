import sys, numpy as np
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dictate'))
import dictate as d
ok = 0; bad = 0
def check(name, cond, extra=''):
    global ok, bad
    if cond: ok += 1
    else: bad += 1
    print(('PASS ' if cond else 'FAIL ') + name, '' if cond else extra)

# --- endpointer with synthetic audio
rng = np.random.default_rng(1)
def noise(sec, a=0.002): return (rng.standard_normal(int(sec*d.RATE))*a).astype('float32')
def voice(sec, a=0.08):
    t = np.arange(int(sec*d.RATE))/d.RATE
    return (a*np.sin(2*np.pi*180*t)*(0.6+0.4*np.sin(2*np.pi*3*t)) + rng.standard_normal(len(t))*0.004).astype('float32')
stream = np.concatenate([noise(1.0), voice(1.5), noise(1.2), voice(0.1), noise(1.2), voice(2.0), noise(1.5)])
ep = d.Endpointer()
utts = []
for i in range(0, len(stream) - d.BLOCK, d.BLOCK):
    utts += ep.feed(stream[i:i+d.BLOCK])
check('two phrases found, click ignored', len(utts) == 2, len(utts))
if len(utts) == 2:
    check('first phrase about 1.5 s plus margin', 1.5 <= len(utts[0])/d.RATE <= 2.4, len(utts[0])/d.RATE)
    check('second phrase about 2 s plus margin', 2.0 <= len(utts[1])/d.RATE <= 2.9, len(utts[1])/d.RATE)

# noisy room: constant hiss should not count as speech forever
hiss = noise(6.0, 0.02)
ep2 = d.Endpointer(); got = []
for i in range(0, len(hiss) - d.BLOCK, d.BLOCK):
    got += ep2.feed(hiss[i:i+d.BLOCK])
check('steady hiss does not make endless speech', not ep2.in_speech or len(ep2.buf) < 400, len(ep2.buf))

# long speech is cut at the limit
long = voice(30.0)
ep3 = d.Endpointer(); got = []
for i in range(0, len(long) - d.BLOCK, d.BLOCK):
    got += ep3.feed(long[i:i+d.BLOCK])
check('very long speech is cut into pieces', len(got) >= 1 and all(len(g)/d.RATE <= 26 for g in got), [len(g)/d.RATE for g in got])

# --- commands
check('new paragraph', d.parse_command('New paragraph.') == ('newline', 2))
check('new line', d.parse_command('new line') == ('newline', 1))
check('polish command', d.parse_command('Polish that.') == ('polish', 0) and d.parse_command('polish the silver') is None)
check('stop', d.parse_command('Stop dictation.') == ('stop', 0))
check('ordinary text is not a command', d.parse_command('I need a new paragraph in the post.') is None)


# --- spoken deleting (worded like the Voice In extension)
check('delete that', d.parse_command('Delete that.') == ('delete_that', 0) and d.parse_command('Scratch that') == ('delete_that', 0))
check('delete everything', d.parse_command('Delete everything.') == ('delete_all', 0) and d.parse_command('clear all') == ('delete_all', 0))
check('delete word and delete last word', d.parse_command('Delete word.') == ('delete_words', 1) and d.parse_command('delete last word') == ('delete_words', 1))
check('delete last N words', d.parse_command('Delete the last three words.') == ('delete_words', 3) and d.parse_command('delete last 12 words') == ('delete_words', 12))
check('select all and undo', d.parse_command('Select all.') == ('select_all', 0) and d.parse_command('Undo.') == ('undo', 0))
check('deleting inside a sentence is not a command',
      d.parse_command('please delete the last word of the report') is None and d.parse_command('I will delete that file') is None)
o = d.Output()
for s in ("The meeting went well", " and we agreed", " to start in March."):
    o.remember(s)
check('delete that removes the last phrase', o.pop_phrase() == 19 and o.tail == "The meeting went well and we agreed", o.tail)
check('delete two words counts the space before each', o.pop_words(2) == 10 and o.tail == "The meeting went well and", o.tail)
check('delete one word counts the space before it', o.pop_words(1) == 4 and o.tail == "The meeting went well", o.tail)
check('after deleting words, delete that has nothing to remove', o.pop_phrase() == 0)
o2 = d.Output(); o2.remember("one two")
check('more words than there are removes only what exists', o2.pop_words(5) == 7 and o2.tail == "", o2.tail)

# --- output spacing and capitals
o = d.Output(["Samarkand"])          # no sentence check (boundary=None): nothing is added at a pause
check('first phrase: no leading space, no stop added', o.prepare('Hello there.') == 'Hello there')
check('next phrase gets a space and a small letter', o.prepare('How are you?') == ' how are you')
o.reset(); o.prepare('I went to the shop and')
check('capital after a pause is lowered', o.prepare('The prices were high.') == ' the prices were high')
o.reset(); o.prepare('I went to see')
check('names from the vocabulary keep their capital', o.prepare('Samarkand for a week.') == ' Samarkand for a week')
o.reset(); o.prepare('And then')
check('I stays capital', o.prepare("I'm not sure.") == " I'm not sure")
o.reset(); o.prepare('First line.'); o.newline(1)
check('no space after a new line', o.prepare('Second line.') == 'Second line')
o.reset()
check('spoken full stop', o.prepare('That is all full stop') == 'That is all.')
check('after a spoken full stop the next phrase keeps its capital', o.prepare('Next thing') == ' Next thing')
check('spoken comma and question mark', d.Output().prepare('well comma is it question mark') == 'well, is it?')
check('ellipsis from Whisper is dropped', d.Output().prepare('...check the difference...') == 'check the difference')
check('a cough is dropped', d.Output().prepare('Ahem.') == '' and d.Output().prepare('[coughs]') == '')
# with a sentence check that says "new sentence here": full stop and a capital
o2 = d.Output([], False, lambda prev, new: '.')
o2.prepare('it looks fine')
check('sentence check adds a full stop and a capital', o2.prepare('I think so') == '. I think so')
check('hallucination dropped', d.Output().prepare('Thank you.') == '')

# --- vocabulary and prompt
import tempfile, os
p = os.path.join(tempfile.mkdtemp(), 'v.txt')
open(p, 'w').write('; comment\nCodex\nChrome\nKodak\'s => Codex\ncrime => Chrome\n\nSamarkand\n')
names = d.load_vocab(p)
check('vocabulary keeps meant words once', names == ['Codex', 'Chrome', 'Samarkand'], names)
pr = d.build_prompt(names, 'We went to Samarkand.')
check('prompt carries names and previous text', 'Codex' in pr and 'We went to Samarkand.' in pr)
print(ok, 'passed,', bad, 'failed')
