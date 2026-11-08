"""Configure the public provider adapter; transport and credential handling stay in llm/."""
from resolveqa.llm import LLMAdapter, load_featherless_api_key


def create_demo_llm(*, real=False):
    adapter = LLMAdapter(use_real=real)
    if real and not load_featherless_api_key(
        adapter.env_file_path, env_key_name=adapter.config.env_key_name,
        strict_permissions=True,
    ):
        raise ValueError(
            'Modo real exige ~/.config/resolveqa/featherless.env com '
            'FEATHERLESS_API_KEY e permissão 0600; chave do ambiente não é usada'
        )
    return adapter
