# Documentation URL Updates

## Task Specification

Replace placeholder text in documentation files with real URLs:
- Repository: https://github.com/knz/battery-sim
- Sponsorship: https://github.com/sponsors/knz
- Releases: https://github.com/knz/battery-sim/releases

Files to update:
- docs/en/install.md (download URL around line 6 comment, line 47 blockquote)
- docs/nl/installatie.md (download URL around line 5 comment, line 47 blockquote)
- docs/en/sponsor.md (sponsorship link around line 17 comment, line 81 blockquote)
- docs/nl/sponsor.md (sponsorship link around line 18 comment, line 86 blockquote)

Also check README.md and docs/README.md for consistency.

## Key Constraints

- Repository is NOT public yet; do not imply public browsability
- Keep Dutch idiomatic in informal je/jouw register
- Preserve dated-source footers and vendor citations
- Do not commit changes

## Files Modified

1. **docs/en/install.md**
   - Updated top-of-file comment: "download URL is a marked placeholder" → "download URL points to the GitHub releases page, which currently has no release"
   - Updated blockquote (line 47): Replaced "This link does not exist yet" placeholder with concrete URL https://github.com/knz/battery-sim/releases and plain statement that no release has been published yet

2. **docs/nl/installatie.md**
   - Updated top-of-file comment: "De downloadlink is een gemarkeerde placeholder: er is nog geen release" → "De downloadlink wijst naar de GitHub-releases-pagina, die op dit moment nog geen release bevat"
   - Updated blockquote (line 47): Replaced Dutch placeholder with URL and statement that releases will appear there once published

3. **docs/en/sponsor.md**
   - Updated top-of-file comment: Removed "There is NO sponsorship channel yet — no account, no FUNDING.yml. The URL is a single marked placeholder line; picking the platform is the user's call."
   - Added new sentence after cost verification paragraph: "Sponsorship is available through GitHub Sponsors at https://github.com/sponsors/knz."
   - Updated blockquote (line 81): Replaced "A sponsorship channel has not been set up yet" placeholder with "You can support the project through [GitHub Sponsors](https://github.com/sponsors/knz). The platform handles recurring monthly contributions and one-time donations."

4. **docs/nl/sponsor.md**
   - Updated top-of-file comment: Removed Dutch equivalent of sponsorship-channel placeholder
   - Added new sentence after cost verification paragraph: "Je kunt het project steunen via GitHub Sponsors: https://github.com/sponsors/knz."
   - Updated blockquote (line 86): Replaced Dutch placeholder with Dutch call to action via GitHub Sponsors with link and brief explanation

## Observations

- README.md and docs/README.md already reference the sponsor pages correctly; no changes needed
- No sentences in checked files imply public browsability of the repository (which is correct — repo is not yet public)
- Remaining grep matches for "nog geen" / "no build" / "does not" are legitimate references to missing macOS/Windows builds and non-existent releases, not stale placeholders
- Dutch register (je/jouw) maintained consistently throughout edits

## Status

Edits complete. Grep verification shows only legitimate remaining references.
