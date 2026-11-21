(function (global) {
  "function" === typeof global;

  function textoDaVaga(vaga) {
    const campos = [
      "titulo", "empresa", "cidade", "descricao", "responsabilidades",
      "requisitos_obrigatorios", "requisitos_preferenciais",
      "competencias_tecnicas", "competencias_tecnicas_originais",
      "tipo_vinculo", "tipo_contrato", "modalidade", "jornada",
    ];
    const partes = [];
    campos.forEach(campo => {
      const valor = vaga[campo];
      if (Array.isArray(valor)) partes.push(...valor.map(String));
      else if (valor != null) partes.push(String(valor));
    });
    return partes.join(" ").toLocaleLowerCase("pt-PT");
  }

  function localizacao(vaga, perfil, hoje) {
    const cidade = String(vaga.cidade || "").toLocaleLowerCase("pt-PT");
    if (vaga.modalidade === "remoto") {
      if (vaga.elegibilidade_portugal === "confirmada") {
        return ["favoravel", "Remoto elegível para Portugal confirmado."];
      }
      return ["por_confirmar", "Remoto indicado, mas elegibilidade em Portugal não confirmada."];
    }
    const locais = perfil.preferencias.localidades_prioritarias;
    if (locais.some(local => cidade.includes(local))) {
      return ["favoravel", `Localização indicada em ${vaga.cidade}.`];
    }
    if (cidade) {
      return ["menos_favoravel", `Localização indicada fora do recorte preferido: ${vaga.cidade}.`];
    }
    return ["desconhecida", "Localização não disponível."];
  }

  function impedimentosObrigatorios(vaga) {
    const valores = Array.isArray(vaga.requisitos_obrigatorios)
      ? vaga.requisitos_obrigatorios
      : [];
    const texto = valores.join(" ").toLocaleLowerCase("pt-PT");
    const impedimentos = [];
    if (/doutorados?\s+h[aá]\s+mais de\s+5\s+anos|doutorado.{0,40}mais de cinco anos/.test(texto)) {
      impedimentos.push("Requisito explícito: Doutorado há mais de cinco anos. Hugo concluiu o doutorado em 2023.");
    }
    if (/certific[aã]o obrigat|certifica[cç][aã]o exigida/.test(texto)) {
      impedimentos.push("Requisito obrigatório de certificação explícito.");
    }
    if (/presencial obrigat/.test(texto)) {
      impedimentos.push("Regime presencial indicado como obrigatório.");
    }
    return impedimentos;
  }

  function afinidade(vaga, perfil) {
    const texto = textoDaVaga(vaga);
    const mapa = {
      "otimizacao matematica": ["otimizacao", "optimization", "otimiza"],
      "modelagem matematica e computacional": ["modelagem", "modelizacao", "simulation", "simulacao"],
      "sistemas eletricos e energeticos": ["sistema eletrico", "sistemas de energia", "energia", "energet"],
      "simulacao computacional": ["simulation", "simulacao", "fem"],
      "python cientifico": ["python"],
      "pyomo": ["pyomo"],
      "pesquisa e desenvolvimento": ["pesquisa", "investigacao", "research", "r&d"],
    };
    const relacionadas = [];
    perfil.competencias_confirmadas.forEach(competencia => {
      const termos = mapa[competencia] || [competencia];
      if (termos.some(termo => texto.includes(termo))) relacionadas.push(competencia);
    });
    const evidencias = relacionadas.map(c => `Evidência disponível: ${c}.`);
    let nivel;
    if (relacionadas.length >= 2) nivel = "alta";
    else if (relacionadas.length > 0) nivel = "moderada";
    else if (texto.trim() && ["engineer", "engenheiro", "cientista", "data", "software",
                              "investigador", "pesquisa", "research", "energia",
                              "otimiz", "sistema", "python"].some(term => texto.includes(term))) {
      nivel = "baixa";
    }
    else nivel = "insuficiente";
    return { nivel, relacionadas, evidencias };
  }

  function prazo(vaga, hoje) {
    const valor = vaga.prazo_candidatura;
    if (!valor) return ["desconhecido", "Prazo de candidatura não disponível."];
    let data;
    const texto = String(valor);
    if (/^\d{4}-\d{2}-\d{2}$/.test(texto)) data = new Date(texto + "T00:00:00Z");
    else if (/^\d{2}\/\d{2}\/\d{4}$/.test(texto)) {
      const [dia, mes, ano] = texto.split("/");
      data = new Date(`${ano}-${mes}-${dia}T00:00:00Z`);
    } else return ["desconhecido", `Prazo com formato não reconhecido: ${valor}`];
    if (Number.isNaN(data.getTime())) return ["desconhecido", `Prazo inválido: ${valor}`];
    const atual = hoje ? new Date(hoje + "T00:00:00Z") : new Date();
    const hojeIso = atual.toISOString().slice(0, 10);
    if (data.toISOString().slice(0, 10) < hojeIso) {
      return ["vencido", `Prazo conhecido: ${texto}, vencido em relação a ${hojeIso}.`];
    }
    return ["vigente", `Prazo conhecido: ${texto}.`];
  }

  function avaliar(vaga, perfil, hoje) {
    const perfilCompleto = perfil || {
      competencias_confirmadas: ["otimizacao matematica"],
      preferencias: { localidades_prioritarias: ["porto", "matosinhos", "gaia", "maia", "aveiro", "braga"] },
    };
    const afinidadeDados = afinidade(vaga, perfilCompleto);
    const impedimentos = impedimentosObrigatorios(vaga);
    const local = localizacao(vaga, perfilCompleto, hoje);
    const prazoDados = prazo(vaga, hoje);
    const obrigatorios = Array.isArray(vaga.requisitos_obrigatorios) ? vaga.requisitos_obrigatorios : [];
    const preferenciais = Array.isArray(vaga.requisitos_preferenciais) ? vaga.requisitos_preferenciais : [];
    const desconhecidos = [];
    if (!Array.isArray(vaga.requisitos_obrigatorios)) desconhecidos.push("Requisitos obrigatórios");
    if (!Array.isArray(vaga.requisitos_preferenciais)) desconhecidos.push("Requisitos preferenciais");

    let classificacao;
    let justificativa;
    if (impedimentos.length) {
      classificacao = "baixa_compatibilidade";
      justificativa = "Há impedimento obrigatório comprovado; a afinidade técnica não elimina a barreira.";
    } else if (!vaga.descricao && obrigatorios.length === 0 && preferenciais.length === 0 &&
               !vaga.competencias_tecnicas) {
      classificacao = "precisa_verificar";
      justificativa = "Informações insuficientes para uma recomendação fundamentada.";
    } else if ((afinidadeDados.nivel === "alta" || afinidadeDados.nivel === "moderada") &&
               local[0] !== "desconhecida" && prazoDados[0] !== "vencido" && desconhecidos.length === 0) {
      classificacao = "prioritaria";
      justificativa = "Afinidade útil com informações suficientes e sem impedimento obrigatório conhecido.";
    } else if ((afinidadeDados.nivel === "alta" || afinidadeDados.nivel === "moderada") && !impedimentos.length) {
      classificacao = "precisa_verificar";
      justificativa = "Há afinidade relevante, mas requisitos, localização ou prazo ainda precisam ser confirmados.";
    } else if (afinidadeDados.nivel === "baixa") {
      classificacao = "baixa_compatibilidade";
      justificativa = "A correspondência disponível é limitada.";
    } else {
      classificacao = "precisa_verificar";
      justificativa = "Informações insuficientes para uma recomendação fundamentada.";
    }

    if (prazoDados[0] === "vencido") {
      classificacao = "baixa_compatibilidade";
      justificativa = "Prazo de candidatura conhecido como vencido.";
    }

    return {
      classificacao,
      afinidade: afinidadeDados.nivel,
      competencias_relacionadas: afinidadeDados.relacionadas,
      evidencias: afinidadeDados.evidencias,
      impedimentos_obrigatorios: impedimentos,
      requisitos_obrigatorios: obrigatorios,
      requisitos_preferenciais: preferenciais,
      informacoes_desconhecidas: [
        ...desconhecidos,
        ...(local[0] === "desconhecida" ? ["Localização"] : []),
        ...(prazoDados[0] === "desconhecido" ? ["Prazo de candidatura"] : []),
      ],
      localizacao: local[0],
      justificativa_local: local[1],
      prazo: prazoDados[0],
      justificativa_prazo: prazoDados[1],
      justificativa,
    };
  }

  const API = { avaliar, afinidade, impedimentosObrigatorios, prazo };
  if (typeof module !== "undefined") module.exports = API;
  global.CompatibilidadeHugo = API;
})(typeof window !== "undefined" ? window : globalThis);
