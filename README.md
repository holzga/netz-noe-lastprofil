# netz-noe-lastprofil

Convert Netz NÖ smart-meter exports (`Jahresverbrauch-YYYY.csv`, 15-minute
intervals in naive local Vienna time) into the Lastprofil upload format
(`Lastprofilvorlage_YYYY.csv`) — ISO-8601 timestamps with the correct
`+01:00`/`+02:00` UTC offset, including daylight-saving transitions.

## Usage

```bash
python3 convert.py
```

The script (Python 3, standard library only) merges all `Jahresverbrauch-*.csv`
files in the folder, derives the correct DST offset for every interval, then
prompts for a date range — either explicit start/end dates or the last *N*
complete days — and writes `Lastprofil_export.csv`.

Non-interactive examples:

```bash
printf '2\n7\n' | python3 convert.py                       # last 7 complete days
printf '1\n2025-06-01\n2025-06-30\n' | python3 convert.py  # June 2025
```

## Output format

ISO-8859-1, CRLF, semicolon-separated:

```
Ende Ablesezeitraum;Messintervall;Abrechnungsmaßeinheit;Verbrauch
2025-01-01T00:15+01:00;QH;KWH;0,02100
```

## Notes

The raw `Jahresverbrauch-*.csv` files and the generated `Lastprofil_export.csv`
contain personal consumption data and are git-ignored.

## License

MIT — see [LICENSE](LICENSE).
