"""Agregado Veiculo: cadastro, validação (RN-15), edição (RN-02) e transições."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from revenda.catalogo.domain.erros import (
    DadosVeiculoInvalidosError,
    TransicaoInvalidaError,
    VeiculoNaoEditavelError,
)
from revenda.catalogo.domain.veiculo import StatusVeiculo, Transicao, Veiculo, validar_dados

AGORA = datetime(2026, 10, 3, 13, 0, tzinfo=UTC)


def novo(**kwargs: object) -> Veiculo:
    dados: dict[str, object] = {
        "marca": "Toyota",
        "modelo": "Corolla XEi 2.0",
        "ano": 2022,
        "cor": "Prata",
        "preco": "124900.00",
        "agora": AGORA,
    }
    dados.update(kwargs)
    return Veiculo.cadastrar(**dados)  # type: ignore[arg-type]


def test_cadastro_nasce_a_venda_com_versao_1_e_evento() -> None:
    veiculo = novo(marca="  Toyota ")
    assert veiculo.status is StatusVeiculo.A_VENDA
    assert veiculo.versao == 1
    assert veiculo.marca == "Toyota"
    assert veiculo.preco == Decimal("124900.00")
    assert veiculo.criado_em == veiculo.atualizado_em == AGORA
    eventos = veiculo.coletar_eventos()
    assert [e.nome for e in eventos] == ["VeiculoCadastrado"]
    assert eventos[0].como_dict()["preco"] == "124900.00"
    assert veiculo.coletar_eventos() == []


@pytest.mark.parametrize(
    ("campo", "valor", "mensagem"),
    [
        ("ano", 1949, "deve estar entre 1950 e 2027"),
        ("ano", 2028, "deve estar entre 1950 e 2027"),
        ("ano", True, "deve ser um número inteiro"),
        ("ano", "2020", "deve ser um número inteiro"),
        ("preco", "0.00", "deve ser maior que zero"),
        ("preco", "-1", "deve ser maior que zero"),
        ("preco", "10.123", "deve ter no máximo 2 casas decimais"),
        ("preco", "abc", "deve ser um valor decimal"),
        ("preco", "NaN", "deve ser um valor decimal"),
        ("preco", 1.5, "deve ser um valor decimal"),
        ("preco", "10000000000.00", "deve ser no máximo 9999999999.99"),
        ("marca", "   ", "não pode ser vazio"),
        ("marca", "x" * 61, "deve ter no máximo 60 caracteres"),
        ("cor", "y" * 31, "deve ter no máximo 30 caracteres"),
        ("modelo", 123, "deve ser texto"),
    ],
)
def test_validacao_rejeita_dados_fora_das_regras(campo: str, valor: object, mensagem: str) -> None:
    with pytest.raises(DadosVeiculoInvalidosError) as erro:
        novo(**{campo: valor})
    assert (campo, mensagem) in erro.value.erros


def test_validacao_acumula_todos_os_erros() -> None:
    with pytest.raises(DadosVeiculoInvalidosError) as erro:
        novo(ano=1900, preco="0", cor="")
    assert {c for c, _ in erro.value.erros} == {"ano", "preco", "cor"}


def test_ano_seguinte_e_aceito_e_preco_inteiro_normalizado() -> None:
    veiculo = novo(ano=2027, preco=50000)
    assert veiculo.ano == 2027
    assert str(veiculo.preco) == "50000.00"


def test_cadastro_sem_campo_obrigatorio() -> None:
    with pytest.raises(DadosVeiculoInvalidosError) as erro:
        novo(cor=None)
    assert erro.value.erros == [("cor", "campo obrigatório")]


def test_edicao_parcial_incrementa_versao() -> None:
    veiculo = novo()
    depois = AGORA + timedelta(minutes=5)
    veiculo.editar(agora=depois, preco="119900.00", cor=" Preto ")
    assert veiculo.preco == Decimal("119900.00")
    assert veiculo.cor == "Preto"
    assert veiculo.marca == "Toyota"
    assert veiculo.versao == 2
    assert veiculo.atualizado_em == depois
    evento = veiculo.coletar_eventos()[-1]
    assert evento.nome == "VeiculoEditado"
    assert evento.como_dict()["campos"] == "cor,preco"


def test_edicao_sem_campos_e_invalida() -> None:
    with pytest.raises(DadosVeiculoInvalidosError):
        novo().editar(agora=AGORA)


@pytest.mark.parametrize("transicao", [Transicao.RESERVAR])
def test_bdd_06_edicao_de_veiculo_reservado_e_negada(transicao: Transicao) -> None:
    """BDD-06 (unidade): veículo reservado não pode ter o preço alterado."""
    veiculo = novo(preco="95000.00")
    veiculo.aplicar(transicao, AGORA)
    with pytest.raises(VeiculoNaoEditavelError) as erro:
        veiculo.editar(agora=AGORA, preco="90000.00")
    assert veiculo.preco == Decimal("95000.00")
    assert "RESERVADO" in str(erro.value)


def test_ciclo_de_transicoes_e_estado_final() -> None:
    veiculo = novo()
    veiculo.reservar(AGORA)
    assert veiculo.status is StatusVeiculo.RESERVADO
    veiculo.liberar(AGORA)
    assert veiculo.status is StatusVeiculo.A_VENDA
    veiculo.reservar(AGORA)
    veiculo.marcar_vendido(AGORA)
    assert veiculo.status is StatusVeiculo.VENDIDO
    assert veiculo.versao == 5
    nomes = [e.nome for e in veiculo.coletar_eventos()]
    assert nomes == [
        "VeiculoCadastrado",
        "VeiculoReservado",
        "VeiculoLiberado",
        "VeiculoReservado",
        "VeiculoVendido",
    ]
    for operacao in (veiculo.reservar, veiculo.liberar, veiculo.marcar_vendido):
        with pytest.raises(TransicaoInvalidaError):
            operacao(AGORA)
    with pytest.raises(VeiculoNaoEditavelError):
        veiculo.editar(agora=AGORA, preco="1.00")


@pytest.mark.parametrize(
    ("operacao", "status_inicial"),
    [("liberar", StatusVeiculo.A_VENDA), ("marcar_vendido", StatusVeiculo.A_VENDA)],
)
def test_transicoes_invalidas_a_partir_de_a_venda(
    operacao: str, status_inicial: StatusVeiculo
) -> None:
    veiculo = novo()
    assert veiculo.status is status_inicial
    with pytest.raises(TransicaoInvalidaError) as erro:
        getattr(veiculo, operacao)(AGORA)
    assert erro.value.atual is StatusVeiculo.A_VENDA


def test_validar_dados_ignora_campos_ausentes() -> None:
    assert validar_dados(ano_corrente=2026).informados() == {}


@pytest.mark.parametrize("campo", ["marca", "modelo", "cor"])
@pytest.mark.parametrize(
    "valor",
    ["a\x00b", "a\x1fb", "a\tb", "a\nb", "Fiat\n", "\x1cFiat", "a\x7fb"],
    ids=["nul", "us", "tab", "lf-meio", "lf-fim", "fs-inicio", "del"],
)
def test_caracteres_de_controle_sao_recusados(campo: str, valor: str) -> None:
    # Antes, um NUL chegava ao PostgreSQL e virava 500; strip() escondia \x1c-\x1f nas pontas.
    with pytest.raises(DadosVeiculoInvalidosError) as erro:
        novo(**{campo: valor})
    assert erro.value.erros == [(campo, "não pode conter caracteres de controle")]
    with pytest.raises(DadosVeiculoInvalidosError):
        novo().editar(agora=AGORA, **{campo: valor})


def test_acentos_e_espacos_internos_continuam_validos() -> None:
    veiculo = novo(marca="Citroën", modelo="C4 Cactus Feel 1.6", cor="Azul Côte d'Azur")
    assert veiculo.marca == "Citroën"


def test_edicao_sem_mudanca_real_nao_gera_versao_nem_evento() -> None:
    veiculo = novo()
    veiculo.coletar_eventos()
    depois = AGORA + timedelta(minutes=5)
    alterou = veiculo.editar(agora=depois, preco="124900", cor=" Prata ", ano=2022)
    assert alterou is False
    assert veiculo.versao == 1
    assert veiculo.atualizado_em == AGORA
    assert veiculo.coletar_eventos() == []
    # Com ao menos um valor diferente, só os campos realmente alterados entram no evento.
    assert veiculo.editar(agora=depois, preco="124900.00", cor="Preto") is True
    assert veiculo.versao == 2
    assert veiculo.coletar_eventos()[-1].como_dict()["campos"] == "cor"
