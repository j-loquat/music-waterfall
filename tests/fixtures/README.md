# Test fixtures

These fixtures are a matched public-domain MIDI and sheet-music PDF for
Beethoven's *Für Elise* (WoO 59). Both files come from the same Mutopia
Project edition, which makes them useful for comparing the direct MIDI path
with the PDF-to-OMR path.

Source record:

- https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=931

Mutopia identifies the composition and this typesetting as public domain. The
first page also states that the typesetter placed the edition in the public
domain and that it is free to distribute, modify, and perform.

## Files

### `midi/fur-elise-mutopia.mid`

- Original URL: https://www.mutopiaproject.org/ftp/BeethovenLv/WoO59/fur_Elise_WoO59/fur_Elise_WoO59.mid
- SHA-256: `1C12C21C7BBF4CF163896732672648A69D497636059837ABD153C71ABE50215A`
- MIDI type: 1
- Tracks: control, upper staff, lower staff
- Approximate MIDI duration: 130.417 seconds

### `pdf/fur-elise-mutopia-letter.pdf`

- Original URL: https://www.mutopiaproject.org/ftp/BeethovenLv/WoO59/fur_Elise_WoO59/fur_Elise_WoO59-let.pdf
- SHA-256: `C5B64F7AD614E8737ED4710E8B7EBEB8359E85C64935767B9E49BFD164B3EBA4`
- Format: US Letter, 3 pages, unencrypted
- Creator: LilyPond 2.18.2

The PDF was rendered and visually checked on 2026-08-10. All three pages are
sharp, complete, upright, and suitable for an optical music recognition test.

Do not add another downloaded fixture without documenting its source, license,
and checksum here.
