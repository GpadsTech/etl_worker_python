# Testes legados fora da suíte ativa

`test_bootstrap.py` acompanha o código em `legacy/bootstrap.py`; apenas seu
import foi ajustado após a movimentação do bootstrap.
O bootstrap e os repositórios legados continuam pendentes e não são executados
por `python -m tests`, `all` ou pela descoberta padrão do unittest.

Esta pasta não é um pacote de testes descoberto automaticamente.
