from chunking import chunk_markdown


def test_bullets_that_fit_are_not_split_between_chunks():
    bullets = [f'- Rule {i}: keep the entire parking instruction together.' for i in range(8)]
    chunks = chunk_markdown('# Policy\n\n## Rules\n\n' + '\n'.join(bullets), 'policy.md', max_chars=180)
    assert len(chunks) > 1
    assert all(len(c.text) <= 180 for c in chunks)
    for bullet in bullets:
        assert sum(bullet in c.body for c in chunks) == 1


def test_prefix_on_every_chunk():
    text = '# Parking policy\n\n## Hours\n\n' + ('Open every day. ' * 60)
    chunks = chunk_markdown(text, 'policy.md', max_chars=180)
    assert len(chunks) > 1
    assert all(c.text.startswith('Source: policy.md\nTitle: Parking policy\nSection: Hours\n\n') for c in chunks)


def test_long_section_respects_cap_and_preserves_content():
    body = ' '.join(f'word{i}' for i in range(600))
    chunks = chunk_markdown('# Policy\n\n## Rules\n\n' + body, 'policy.md', max_chars=200)
    assert all(len(c.text) <= 200 and not c.oversized for c in chunks)
    assert ' '.join(c.body for c in chunks).split() == body.split()


def test_tables_kept_whole():
    table = '| Permit | Price |\n|---|---|\n' + '\n'.join(f'| Type {i} | $100 |' for i in range(20))
    chunks = chunk_markdown('# Policy\n\n## Permits\n\nBefore.\n\n' + table + '\n\nAfter.', 'policy.md', max_chars=160)
    tables = [c for c in chunks if '| Permit |' in c.body]
    assert len(tables) == 1 and tables[0].body == table
    assert tables[0].oversized
    assert all(c.body == table or len(c.text) <= 160 for c in chunks)
