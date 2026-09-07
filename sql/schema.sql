CREATE TABLE IF NOT EXISTS consultas_nfe (
    chave CHAR(44) PRIMARY KEY,
    status VARCHAR(16) NOT NULL
        CHECK (status IN ('PENDENTE', 'DEBITO', 'SEM_DEBITO', 'ERRO')),
    valor_pagar NUMERIC(14, 2)
        CHECK ((status = 'DEBITO') = (valor_pagar IS NOT NULL)),
    detalhes TEXT,
    tentativas INTEGER NOT NULL DEFAULT 0,
    consultada_em TIMESTAMPTZ,
    atualizada_em TIMESTAMPTZ NOT NULL DEFAULT now()
);