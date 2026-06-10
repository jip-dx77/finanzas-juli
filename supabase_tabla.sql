-- Ejecutá esto en el SQL Editor de Supabase
-- Dashboard > SQL Editor > New query

CREATE TABLE gastos (
  id         BIGSERIAL PRIMARY KEY,
  concepto   TEXT NOT NULL,
  monto      NUMERIC(12, 2) NOT NULL,
  categoria  TEXT NOT NULL DEFAULT 'otros',
  fecha      DATE NOT NULL DEFAULT CURRENT_DATE,
  mes        INTEGER NOT NULL,
  anio       INTEGER NOT NULL,
  fuente     TEXT DEFAULT 'manual',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para consultas rápidas del dashboard
CREATE INDEX idx_gastos_mes_anio ON gastos (anio, mes);
CREATE INDEX idx_gastos_fecha    ON gastos (fecha);
CREATE INDEX idx_gastos_categoria ON gastos (categoria);

-- Habilitar lectura pública (el dashboard la usa)
ALTER TABLE gastos ENABLE ROW LEVEL SECURITY;

CREATE POLICY "lectura publica" ON gastos
  FOR SELECT USING (true);

CREATE POLICY "insercion autenticada" ON gastos
  FOR INSERT WITH CHECK (true);
