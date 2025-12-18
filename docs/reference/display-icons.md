# Customizing Connector Display Icons

Several connectors support a `DSXCONNECTOR_DISPLAY_ICON` setting that lets you surface a custom icon on the dsx-connect UI card. The value must be a data URI containing an SVG that passes the frontend sanitizer (`<svg>` only — no scripts or external references).

## 1. Prepare your SVG
- Keep it simple (single `<svg>` element, no embedded scripts).
- For consistency with other cards, use a 48×48 view box.

Example SVG:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
  <linearGradient id="onedriveGradient" x1="4" x2="44" y1="24" y2="24">
    <stop offset="0" stop-color="#1570d9" />
    <stop offset="1" stop-color="#1b4bb8" />
  </linearGradient>
  <path fill="url(#onedriveGradient)" d="M17.2 20.3a12.4 12.4 0 0 1 22.5 4.3A9.8 9.8 0 0 1 44 43H16.7A12.7 12.7 0 0 1 17.2 20.3Z" />
  <path fill="#2d8cff" d="M13.6 21.5a8.9 8.9 0 0 1 14.3-5.3A12.3 12.3 0 0 0 17.4 41H6.3a8.3 8.3 0 0 1 7.3-19.5Z" />
</svg>
```

## 2. Percent-encode the SVG
`DSXCONNECTOR_DISPLAY_ICON` expects a percent-encoded SVG with the prefix `data:image/svg+xml;utf8,`.

Ask ChatGPT to generate the data URI for you or use an online URL encoder and prepend `data:image/svg+xml;utf8,` to the result.

Example output:

```
data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%2048%2048%22%3E...
```

## 3. Set the environment variable
In the connector’s `.dev.env` or deployment values:

```bash
DSXCONNECTOR_DISPLAY_ICON="data:image/svg+xml;utf8,%3Csvg%20...%3E"
```

Restart the connector and the UI card will render the custom icon, provided the SVG passes dsx-connect’s sanitizer.
