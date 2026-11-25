-- Meu perfil (25/11/2026): telefone e foto da própria conta.
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente: pode rodar de novo sem efeito.
--
-- telefone: só dígitos (DDD + número, 10 ou 11), opcional.
-- usuario_foto: tabela própria para a foto não vir junto em todo
--   select("*") de users. O navegador já manda a foto cortada em quadrado e
--   reduzida a 256px; o servidor reabre com o Pillow e regrava em JPEG, então
--   aqui só entra imagem decodificável e sem metadados (EXIF com GPS, por
--   exemplo). Guardada em base64 (~40 KB).

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS telefone text NULL;

CREATE TABLE IF NOT EXISTS public.usuario_foto (
  user_id       uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  jpeg_b64      text NOT NULL,
  atualizada_em timestamptz NOT NULL DEFAULT now()
);
