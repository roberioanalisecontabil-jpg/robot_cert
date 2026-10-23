# Vídeos da wiki do Certguard

Fonte dos três vídeos curtos de `/wiki-certguard`. Cada vídeo é uma página HTML que desenha réplicas das
telas do portal e da bandeja em movimento (motor da skill `video-apresentacao`). Nada toca o sistema real:
empresas, CNPJs e e-mails são **fictícios** (`exemplo.com`, `10.000.0xx/0001-xx`). Sem música.

| Roteiro | Página | MP4 publicado | Tutorial |
|---|---|---|---|
| `bandeja` | `bandeja.html` | `static/wiki/video-bandeja.mp4` | `templates/wiki/bandeja.html` |
| `vencimentos` | `vencimentos.html` | `static/wiki/video-vencimentos.mp4` | `templates/wiki/acompanhamento.html` |
| `login` | `login.html` | `static/wiki/video-login.mp4` | `templates/wiki/primeiros-passos.html` |

A capa de cada vídeo é `static/wiki/video-<nome>.jpg`.

## Ver

Sirva a pasta (`python -m http.server 8765 --directory scripts/wiki_videos`, as fontes não carregam por
`file://`) e abra `http://127.0.0.1:8765/bandeja.html`. `?t=20` abre no segundo 20.

## Mudar

Tudo está em `script.js`:
- seção 3: as réplicas (`htmlPaginas()`), copiadas de `templates/index.html`, `vencidos.html`,
  `colaborador_certificados.html`, `login.html`, `static/ui-common.js` (Defina sua senha) e
  `estacao/bandeja.py` (menu do ícone e aviso do Windows). Mudou o rótulo no portal, mude aqui.
- seção 4: as cenas (`SCENES`), as cores de transição (`MODULOS_COR`) e os três roteiros (`ROTEIROS`).

Depois de mudar, confira com o `verificar.py` da skill (`LIMPO` = sem erro de console e sem alvo cortado).

## Gravar

```
python scripts/wiki_videos/gravar.py bandeja static/wiki/video-bandeja.mp4
ffmpeg -ss 31 -i static/wiki/video-bandeja.mp4 -frames:v 1 -q:v 4 static/wiki/video-bandeja.jpg
```

`gravar.py` fotografa quadro a quadro (30 qps) direto em 1280x720 e codifica H.264 sem áudio; cada vídeo
fica abaixo de 4 MB. Os vídeos são incluídos na página pela macro `video(id, titulo)` de
`templates/wiki/_macros.html`, e `tests/test_wiki.py` confere que cada vídeo citado tem MP4 e capa.
