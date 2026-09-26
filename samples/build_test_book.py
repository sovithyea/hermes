"""Build samples/black-dragons-choice.epub — an original two-chapter test story.

It exercises the hard cases for the director: a first-person narrator, telepathic dragon
speech in italics, the narrator's own italic replies, untagged back-and-forth dialogue,
and several speakers of different genders.

    uv run python samples/build_test_book.py
"""

from pathlib import Path

from ebooklib import epub

CHAPTERS = [
    ("Chapter One", """
<p>The wind at the top of the parapet tasted like rain and iron, and I hated it immediately.</p>
<p>Forty cadets stood shoulder to shoulder on a ledge built for twenty. Below us, the valley fell away into mist so thick I couldn't see where the stone ended and the drop began. I counted my breaths. I counted the rivets on the pack of the boy in front of me. I counted anything that wasn't the distance to the ground.</p>
<p>“If you're going to throw up, Maren, aim left,” Ione said, bumping my shoulder with hers. “Brask is standing to your left.”</p>
<p>“I'm not going to throw up.”</p>
<p>“Your face says otherwise.”</p>
<p>“My face is just cold.”</p>
<p>She grinned, all teeth and freckles, and tightened the strap under her chin. Ione had wanted this since we were eight years old. I had wanted a quiet life in the archives, surrounded by books that didn't try to kill me. We had both, somehow, ended up on the same ledge.</p>
<p>Professor Hale walked the length of the line with her hands clasped behind her back. She didn't look down. She never looked down.</p>
<p>“Cadets,” she called, and the word carried over the wind like a blade. “In a moment, the first of the wild flights will pass beneath this wall. Some of you will be chosen. Most of you will not. Those who are not chosen will walk back down the stairs and go home with their dignity intact.”</p>
<p>“And the ones who fall?” someone asked from the end of the line.</p>
<p>Hale paused. “Will not need the stairs.”</p>
<p>Nobody laughed.</p>
<p>Brask leaned toward me, close enough that I could smell the oil on his armor. He was a head taller than me and twice as wide, and he had made it his personal mission since the first week to remind me that I didn't belong here.</p>
<p>“Still time to go home, archive girl,” he murmured. “Nobody would blame you. Well. I would. But nobody important.”</p>
<p>“Thank you, Brask,” I said. “That's the nicest thing you've ever said to me.”</p>
<p>“It wasn't a compliment.”</p>
<p>“I know. I'm just setting low expectations.”</p>
<p>Ione snorted. Brask straightened, jaw tight, and faced forward again.</p>
<p>Then the air changed.</p>
<p>It's hard to describe if you haven't felt it. A pressure behind the eyes, a hum in the teeth, the way the hair on your arms rises before lightning. The mist below us began to churn. Something enormous moved through it, and then something else, and then the valley was full of wings.</p>
<p>They rose past the wall in a storm of color—copper and slate and green like deep water—so close that the wind of their passing nearly took me off my feet. I grabbed the stone. Beside me, Ione was laughing, a wild, breathless sound.</p>
<p>And then one of them stopped.</p>
<p>It hung in the air directly in front of me, black as a moonless night, its wings beating slow and heavy. Its eyes were molten gold, and they were fixed on me.</p>
<p><em>You are smaller than I expected.</em></p>
<p>The voice didn't come through my ears. It came from somewhere behind my ribs, deep and rough, like boulders grinding together at the bottom of a river.</p>
<p><em>Please don't be talking to me,</em> I thought. <em>Please be talking to Brask.</em></p>
<p><em>I do not talk to fools. Step forward, little archivist.</em></p>
<p>“Maren,” Ione whispered. “Maren, is it—is he—”</p>
<p>“I think so,” I said. My voice cracked in the middle.</p>
<p>“Well, don't just stand there!”</p>
<p>Professor Hale had stopped walking. For the first time since I'd known her, she looked surprised. “Cadet Vale,” she said slowly. “It appears you have been chosen by Skarth.”</p>
<p>“Is that good?”</p>
<p>“It is,” Hale said, “unprecedented.”</p>
<p><em>Tell her I can hear her,</em> the dragon said. <em>And that I have been chosen by no one. I do the choosing.</em></p>
<p>I swallowed hard, let go of the wall, and stepped to the edge.</p>
"""),
    ("Chapter Two", """
<p>The flight barracks were quiet after midnight, which was the only reason I heard the footsteps behind me in the corridor.</p>
<p>“You're out past curfew,” said a low voice.</p>
<p>I spun around. Kael Dunmore leaned against the doorframe of the map room, arms folded, the lantern light catching the scar that ran through his left eyebrow. He was a third-year, a squad leader, and the only person in the entire academy who had never once looked surprised to see me.</p>
<p>“So are you,” I said.</p>
<p>“I'm a squad leader. I'm allowed to be out past curfew.”</p>
<p>“That seems unfair.”</p>
<p>“Most things here are.” He pushed off the door and walked toward me, unhurried. “Why aren't you asleep?”</p>
<p>“Why aren't you?”</p>
<p>“Because someone keeps pacing outside my room.”</p>
<p>Heat crept up my neck. “I wasn't pacing. I was thinking. With my feet.”</p>
<p>For a second, the corner of his mouth lifted. It was gone almost before I saw it.</p>
<p><em>He is laughing at you,</em> Skarth observed from somewhere far above the barracks, his voice heavy with sleep.</p>
<p><em>He is not. Go back to sleep.</em></p>
<p><em>I am a dragon. I sleep when I choose.</em></p>
<p>“He's talking to you right now, isn't he?” Kael asked quietly.</p>
<p>“How can you tell?”</p>
<p>“You get a look. Like you're listening to a song nobody else can hear.” He stopped an arm's length away. “My dragon does the same thing to me. Vesh has opinions about everyone.”</p>
<p>“What does she think of me?”</p>
<p>He hesitated. “She thinks you're going to get yourself killed.”</p>
<p>“Wonderful.”</p>
<p>“She also thinks you might be the most interesting rider this academy has seen in fifty years.” He tilted his head. “I haven't decided which of those is true yet.”</p>
<p>“Maybe both,” I whispered.</p>
<p>“Maybe.” He glanced toward the dark end of the corridor, and his voice dropped even lower. “Listen to me, Maren. Tomorrow they'll put you on the flight line with the rest of the first-years, and there are people here who don't think a girl from the archives should have the strongest dragon in the valley. Watch your back. Watch Brask especially.”</p>
<p>“Are you warning me or threatening me?”</p>
<p>“If I were threatening you,” he said, “you'd know.”</p>
<p><em>I like this one,</em> Skarth rumbled. <em>He is honest. It is very rare among humans.</em></p>
<p>I rolled my eyes. “Goodnight, Kael.”</p>
<p>“Goodnight, archivist.”</p>
<p>I didn't look back as I walked away, but I could feel him watching me all the way to the stairs.</p>
"""),
]

# Who really says each dialogue / italic line, in order — used by tests/eval_test_book.py.
GOLD = {
    1: ["Ione", "Ione", "Maren", "Ione", "Maren", "Professor Hale", "Professor Hale", "Unknown",
        "Professor Hale", "Brask", "Brask", "Maren", "Maren", "Brask", "Maren", "Skarth", "Maren", "Maren",
        "Skarth", "Ione", "Ione", "Maren", "Ione", "Professor Hale", "Professor Hale", "Maren",
        "Professor Hale", "Professor Hale", "Skarth", "Skarth"],
    2: ["Kael", "Maren", "Kael", "Maren", "Kael", "Kael", "Maren", "Kael", "Maren", "Skarth", "Maren",
        "Skarth", "Kael", "Maren", "Kael", "Kael", "Maren", "Kael", "Maren", "Kael", "Kael", "Maren",
        "Kael", "Kael", "Maren", "Kael", "Kael", "Skarth", "Skarth", "Maren", "Kael"],
}


def build(out: Path) -> Path:
    book = epub.EpubBook()
    book.set_identifier("hermes-test-black-dragons-choice")
    book.set_title("The Black Dragon's Choice")
    book.set_language("en")
    book.add_author("Hermes test fixture")
    items = []
    for i, (title, body) in enumerate(CHAPTERS, start=1):
        item = epub.EpubHtml(title=title, file_name=f"ch{i}.xhtml", lang="en")
        item.content = f"<html><body><h1>{title}</h1>{body}</body></html>"
        book.add_item(item)
        items.append(item)
    book.toc = items
    book.spine = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(out), book)
    return out


if __name__ == "__main__":
    print(build(Path(__file__).with_name("black-dragons-choice.epub")))
