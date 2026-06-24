# Scripture Source

The congregation sidebar needs to show the full Bible passage referenced in a
sermon. For the open-source POC, the Chinese scripture source is:

- Translation: 新标点和合本（简体） / Chinese Union Version (simplified)
- eBible ID: `cmn-cu89s`
- Details: <https://ebible.org/find/details.php?id=cmn-cu89s>
- Download: <https://ebible.org/Scriptures/cmn-cu89s_vpl.zip>
- License status shown by eBible: Public Domain

The full Bible index is generated into `data/scripture/cmn-cu89s.json` and copied
into the Cloud Run container by the Dockerfile. The browser does not load that
full file directly; it requests chapters through the backend API:

- `GET /api/scripture/cmn-cu89s`
- `GET /api/scripture/cmn-cu89s/books`
- `GET /api/scripture/cmn-cu89s/Numbers/16`
- `GET /api/scripture/cmn-cu89s/民数记/16`

The same full JSON can also be uploaded to GCS as a durable public-domain source
artifact, for example `gs://<bucket>/scripture/cmn-cu89s/cmn-cu89s.json`.

For fast static previews, `scripts/build_scripture_index.py` also builds a small
referenced-passage browser slice:

```bash
python3 scripts/build_scripture_index.py \
  --out web/scripture-cmn-cu89s.generated.js \
  --full-out data/scripture/cmn-cu89s.json \
  --ref "Numbers 16" \
  --ref "Numbers 16:48"
```

Use `--zip /path/to/cmn-cu89s_vpl.zip` to build from an already downloaded
archive. The generated browser file includes source metadata and only the
requested references; the generated backend JSON contains all 66 books.

`wd.bible` is not used as a text source for redistribution. Its CUNPS pages show
`Copyright © 1995 Hong Kong Bible Society. Used by permission`, which means the
site has permission to display the text, but that permission does not transfer to
this project.

UI attribution should read:

`中文圣经：新标点和合本（简体） · eBible.org cmn-cu89s · Public Domain`
