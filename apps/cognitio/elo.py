"""Sistema Elo para modelagem do estudante: alternativa mais simples ao BKT, validada da mesma forma.

Pergunta (a mesma do BKT): qual a probabilidade de a próxima evidência do estudante numa habilidade ser um
acerto?

Por que comparar com o BKT: a revisão de Pelánek (2017, UMUAI 27, 313–350, doi:10.1007/s11257-017-9193-2)
mostra que modelos logísticos simples muitas vezes preveem tão bem quanto o BKT. O Elo trata cada resposta
como uma partida entre o estudante e a habilidade e estima, ao mesmo tempo, a proficiência do estudante e a
dificuldade da habilidade. A revisão de Pelánek (2016, Computers & Education 98, 169–179,
doi:10.1016/j.compedu.2016.03.017) o descreve como "simples, robusto e eficaz" em sistemas adaptativos, e
Papoušek, Pelánek & Stanislav (2014, EDM) o usaram para estimar conhecimento prévio.

Método (puro Python):

- P(acerto) = σ(θ_estudante − d_habilidade). Depois de cada evidência: θ += K·(resultado − P) e
  d −= K·(resultado − P).
- **Função de incerteza** K(n) = a / (1 + b·n), em que n é o número de evidências já vistas daquele
  estudante ou daquela habilidade: o primeiro resultado move muito a estimativa e os seguintes, cada vez
  menos (Pelánek, 2016).
- a e b escolhidos em grade pela verossimilhança no treino. O acerto é a mesma regra do BKT
  (``bkt.CORRECT``).
- **Validação temporal idêntica à do BKT:** mesmo corte (70% das observações no treino) e mesmas
  referências (taxa base e "repetir o último resultado"). Cada previsão do teste é feita antes de ver a
  própria resposta, então os dois modelos são comparáveis no mesmo conjunto.
- **Limite:** o Elo global usa uma proficiência por estudante para todas as habilidades. Funciona quando
  as habilidades se parecem (um componente) e perde quando o estudante é forte numa e fraco noutra. Por
  isso a comparação com o BKT, que é por habilidade, é feita com os dados da escola.

Sem dados suficientes, fica em modo exploratório (os mesmos mínimos do BKT). Com dados, fica "experimental"
até a aprovação humana registrada. ``synthetic_check`` só confere que o código recupera dificuldades
conhecidas; não diz nada sobre estudantes reais.
"""

import math
import random

from .bkt import CORRECT, MIN_OBS, MIN_SEQ, MIN_TEST, sequences
from .models import ModelRun
from .predictive import metrics

NAME = "elo_proximo_acerto"
VERSION = "1.0"
GRID = {"a": [0.1, 0.2, 0.4, 0.8, 1.2, 1.6], "b": [0.02, 0.05, 0.1, 0.2]}


def _sigma(x):
    return 1 / (1 + math.exp(-max(min(x, 30), -30)))


def run_online(obs, a, b):
    """Percorre [(data, estudante, habilidade, 0/1)] em ordem e devolve a previsão feita ANTES de cada
    resposta, com o estado final (proficiências, dificuldades e contagens)."""
    theta, diff, n_s, n_i = {}, {}, {}, {}
    preds = []
    for _, sid, iid, o in obs:
        p = _sigma(theta.get(sid, 0.0) - diff.get(iid, 0.0))
        preds.append(p)
        ks = a / (1 + b * n_s.get(sid, 0))
        ki = a / (1 + b * n_i.get(iid, 0))
        theta[sid] = theta.get(sid, 0.0) + ks * (o - p)
        diff[iid] = diff.get(iid, 0.0) - ki * (o - p)
        n_s[sid] = n_s.get(sid, 0) + 1
        n_i[iid] = n_i.get(iid, 0) + 1
    return preds, {"theta": theta, "diff": diff}


def _loglik(ys, ps):
    return sum(math.log(min(max(p if y else 1 - p, 1e-6), 1)) for y, p in zip(ys, ps))


def fit(obs):
    """(a, b) de maior verossimilhança no conjunto dado, em grade."""
    ys = [o for *_, o in obs]
    best, best_ll = None, -math.inf
    for a in GRID["a"]:
        for b in GRID["b"]:
            ll = _loglik(ys, run_online(obs, a, b)[0])
            if ll > best_ll:
                best, best_ll = (a, b), ll
    return best


def flatten(seqs):
    """Todas as observações em ordem de data (empates na ordem estável estudante, habilidade)."""
    return sorted(((d, sid, iid, o) for (sid, iid), s in seqs.items() for d, o in s),
                  key=lambda t: (t[0], t[1], t[2]))


def train_and_validate(school, user=None):
    seqs = sequences(school)
    obs = flatten(seqs)
    run = ModelRun(school=school, name=NAME, version=VERSION)
    n = len(obs)
    if n < MIN_OBS or len(seqs) < MIN_SEQ:
        run.status = ModelRun.Status.INSUFFICIENT
        run.n_train = n
        run.notes = (f"{n} observações em {len(seqs)} sequências estudante-habilidade. São necessárias pelo menos "
                     f"{MIN_OBS} observações e {MIN_SEQ} sequências (os mesmos mínimos do BKT). Modo exploratório.")
        run.save()
        return run
    cutoff = sorted(d for d, *_ in obs)[int(n * 0.7)]  # o mesmo corte do BKT
    train = [t for t in obs if t[0] < cutoff]
    a, b = fit(train)
    preds, state = run_online(obs, a, b)
    y = [o for (d, *_rest, o) in obs if d >= cutoff]
    scores = [p for (d, *_rest), p in zip(obs, preds) if d >= cutoff]
    run.cutoff = cutoff
    run.n_train, run.n_test = n - len(y), len(y)
    run.positives = sum(y)
    if len(y) < MIN_TEST or len(set(y)) < 2:
        run.status = ModelRun.Status.INSUFFICIENT
        run.notes = (f"Teste com {len(y)} observações depois de {cutoff:%d/%m/%Y}; são necessárias {MIN_TEST}, com "
                     "acertos e erros. Modo exploratório.")
        run.save()
        return run
    # Referências iguais às do BKT: taxa de acerto do treino e "repetir o último resultado" da sequência.
    rate = sum(o for *_, o in train) / max(len(train), 1)
    last, prev = [], {}
    for d, sid, iid, o in obs:
        if d >= cutoff:
            last.append(float(prev[(sid, iid)]) if (sid, iid) in prev else rate)
        prev[(sid, iid)] = o
    run.metrics = metrics(y, scores)
    run.metrics["log_loss"] = -_loglik(y, scores) / len(y)
    run.baseline = {"taxa_base": metrics(y, [rate] * len(y)), "ultimo_resultado": metrics(y, last)}
    run.coefficients = {"a": a, "b": b, "acerto_minimo": CORRECT,
                        "dificuldades": {str(k): round(v, 3) for k, v in state["diff"].items()}}
    auc, auc_last = run.metrics.get("auc") or 0, run.baseline["ultimo_resultado"].get("auc") or 0.5
    bkt = (ModelRun.objects.filter(school=school, name="bkt_proximo_acerto", cutoff=cutoff, n_test=len(y))
           .exclude(status=ModelRun.Status.INSUFFICIENT).first())
    versus = ""
    if bkt and bkt.metrics.get("auc") is not None:
        versus = (f"No mesmo teste, AUC do Elo {auc:.3f} contra {bkt.metrics['auc']:.3f} do BKT "
                  f"(log-loss {run.metrics['log_loss']:.3f} contra {bkt.metrics.get('log_loss', float('nan')):.3f}). ")
    run.status = ModelRun.Status.EXPERIMENTAL
    run.notes = ("Validado tecnicamente com o mesmo corte temporal do BKT. " + versus
                 + ("Superou 'repetir o último resultado' em AUC. " if auc > auc_last else
                    "NÃO superou 'repetir o último resultado' em AUC: não usar. ")
                 + "Uso só depois de aprovação pedagógica registrada.")
    run.save()
    return run


def synthetic_check(n_students=200, n_items=12, per_student=10, seed=5):
    """Gera respostas SINTÉTICAS de um modelo de Rasch com dificuldades conhecidas e devolve a correlação de
    postos (Spearman) entre as dificuldades verdadeiras e as estimadas."""
    rnd = random.Random(seed)
    true_d = {i: rnd.gauss(0, 1) for i in range(n_items)}
    abilities = {s: rnd.gauss(0, 1) for s in range(n_students)}
    obs, day = [], 0
    for _ in range(per_student):
        for s in range(n_students):
            i = rnd.randrange(n_items)
            day += 1
            obs.append((day, s, i, 1 if rnd.random() < _sigma(abilities[s] - true_d[i]) else 0))
    _, state = run_online(obs, *fit(obs))
    return _spearman([true_d[i] for i in range(n_items)], [state["diff"].get(i, 0.0) for i in range(n_items)])


def _spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda k: v[k])
        r = [0] * len(v)
        for pos, k in enumerate(order):
            r[k] = pos
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    return 1 - 6 * sum((p - q) ** 2 for p, q in zip(rx, ry)) / (n * (n * n - 1))
