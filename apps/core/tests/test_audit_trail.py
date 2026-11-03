"""Histórico de auditoria de um registro: só da mesma escola e de depois que ele foi criado.

No SQLite, uma migração que recria uma tabela vazia faz a numeração recomeçar. Na cópia de teste, uma
solicitação nova (nº 1, escola 3) mostrou no histórico o registro de uma solicitação apagada da escola 1.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.communication.models import ServiceRequest
from apps.communication.tests.test_communication import CommunicationBase
from apps.core.models import AuditLog, Role, audit_trail


class AuditTrailTests(CommunicationBase):
    def test_reused_number_does_not_inherit_another_schools_history(self):
        old = ServiceRequest.objects.create(school=self.school_b, requester=self.resp_b, title="Pedido antigo",
                                            description="x")
        AuditLog.objects.create(user=self.resp_b, school=self.school_b, action="create",
                                target_type="ServiceRequest", target_id=str(old.pk), detail="Solicitação 'Antiga B'")
        pk = old.pk
        old.delete()
        new = ServiceRequest.objects.create(pk=pk, school=self.school, requester=self.resp, title="Pedido novo",
                                            description="y")
        AuditLog.objects.create(user=self.resp, school=self.school, action="create", target_type="ServiceRequest",
                                target_id=str(pk), detail="Solicitação 'Nova A'")
        self.assertEqual([l.detail for l in audit_trail(new)], ["Solicitação 'Nova A'"])
        self.client.force_login(self.sec)
        page = self.client.get(reverse("communication:request_detail", args=[pk]))
        self.assertContains(page, "Nova A")
        self.assertNotContains(page, "Antiga B")

    def test_entries_from_before_the_record_existed_are_left_out(self):
        req = ServiceRequest.objects.create(school=self.school, requester=self.resp, title="P", description="z")
        early = AuditLog.objects.create(user=self.resp, school=self.school, action="create",
                                        target_type="ServiceRequest", target_id=str(req.pk), detail="De antes")
        AuditLog.objects.filter(pk=early.pk).update(created_at=req.created_at.replace(year=req.created_at.year - 1))
        system = get_user_model().objects.create_user("sistema", password="senha-forte-1", role=Role.ADMIN)
        AuditLog.objects.create(user=system, school=None, action="update", target_type="ServiceRequest",
                                target_id=str(req.pk), detail="Conta sem escola")
        self.assertEqual([l.detail for l in audit_trail(req)], ["Conta sem escola"])
