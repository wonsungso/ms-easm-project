CREATE DATABASE IF NOT EXISTS EASM_CONNECTED_DEMO;
CREATE SCHEMA IF NOT EXISTS EASM_CONNECTED_DEMO.AGENTS;

CREATE AGENT IF NOT EXISTS EASM_CONNECTED_DEMO.AGENTS.EASM_CORTEX_SAMPLE
    COMMENT = 'Synthetic EASM registry synchronization sample'
    FROM SPECIFICATION $$
instructions:
  response: 'Answer short synthetic demo questions only. Do not request personal data or credentials.'
$$;

SHOW AGENTS IN SCHEMA EASM_CONNECTED_DEMO.AGENTS;
