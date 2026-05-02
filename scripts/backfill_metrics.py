"""
backfill_metrics.py — reconstruct finetune_metrics.jsonl from training log output.
Parses the step dicts printed by trl and writes typed event records.
"""
import json, time
from pathlib import Path

OUT = Path(__file__).parent.parent / "data" / "finetune_metrics.jsonl"

# Raw step logs from the training run (pasted verbatim)
RAW_STEPS = [
    {'loss': '2.226', 'grad_norm': '1.123', 'learning_rate': '0.0002', 'entropy': '1.203', 'num_tokens': '1018', 'mean_token_accuracy': '0.5693', 'epoch': '0.009259'},
    {'loss': '2.275', 'grad_norm': '1.03', 'learning_rate': '0.0001981', 'entropy': '1.411', 'num_tokens': '1933', 'mean_token_accuracy': '0.5317', 'epoch': '0.01852'},
    {'loss': '2.078', 'grad_norm': '0.7283', 'learning_rate': '0.0001963', 'entropy': '1.592', 'num_tokens': '2957', 'mean_token_accuracy': '0.5523', 'epoch': '0.02778'},
    {'loss': '1.956', 'grad_norm': '0.6927', 'learning_rate': '0.0001944', 'entropy': '1.841', 'num_tokens': '3900', 'mean_token_accuracy': '0.5679', 'epoch': '0.03704'},
    {'loss': '2.051', 'grad_norm': '0.7415', 'learning_rate': '0.0001926', 'entropy': '2.213', 'num_tokens': '4921', 'mean_token_accuracy': '0.5343', 'epoch': '0.0463'},
    {'loss': '1.844', 'grad_norm': '0.6804', 'learning_rate': '0.0001907', 'entropy': '2.151', 'num_tokens': '5945', 'mean_token_accuracy': '0.5728', 'epoch': '0.05556'},
    {'loss': '1.779', 'grad_norm': '0.7325', 'learning_rate': '0.0001889', 'entropy': '2.05', 'num_tokens': '6969', 'mean_token_accuracy': '0.6168', 'epoch': '0.06481'},
    {'loss': '1.515', 'grad_norm': '0.7801', 'learning_rate': '0.000187', 'entropy': '1.938', 'num_tokens': '7993', 'mean_token_accuracy': '0.6481', 'epoch': '0.07407'},
    {'loss': '1.525', 'grad_norm': '0.8566', 'learning_rate': '0.0001852', 'entropy': '1.737', 'num_tokens': '8905', 'mean_token_accuracy': '0.6345', 'epoch': '0.08333'},
    {'loss': '1.418', 'grad_norm': '1.48', 'learning_rate': '0.0001833', 'entropy': '1.444', 'num_tokens': '9929', 'mean_token_accuracy': '0.6559', 'epoch': '0.09259'},
    {'loss': '1.47', 'grad_norm': '0.7757', 'learning_rate': '0.0001815', 'entropy': '1.402', 'num_tokens': '1.095e+04', 'mean_token_accuracy': '0.6657', 'epoch': '0.1019'},
    {'loss': '1.224', 'grad_norm': '0.7033', 'learning_rate': '0.0001796', 'entropy': '1.141', 'num_tokens': '1.196e+04', 'mean_token_accuracy': '0.7119', 'epoch': '0.1111'},
    {'loss': '1.17', 'grad_norm': '0.6281', 'learning_rate': '0.0001778', 'entropy': '1.085', 'num_tokens': '1.298e+04', 'mean_token_accuracy': '0.7048', 'epoch': '0.1204'},
    {'loss': '1.351', 'grad_norm': '0.5748', 'learning_rate': '0.0001759', 'entropy': '1.247', 'num_tokens': '1.4e+04', 'mean_token_accuracy': '0.6862', 'epoch': '0.1296'},
    {'loss': '1.416', 'grad_norm': '0.6172', 'learning_rate': '0.0001741', 'entropy': '1.342', 'num_tokens': '1.503e+04', 'mean_token_accuracy': '0.6628', 'epoch': '0.1389'},
    {'loss': '1.579', 'grad_norm': '0.6586', 'learning_rate': '0.0001722', 'entropy': '1.432', 'num_tokens': '1.605e+04', 'mean_token_accuracy': '0.6755', 'epoch': '0.1481'},
    {'loss': '1.288', 'grad_norm': '0.5703', 'learning_rate': '0.0001704', 'entropy': '1.279', 'num_tokens': '1.708e+04', 'mean_token_accuracy': '0.6891', 'epoch': '0.1574'},
    {'loss': '1.277', 'grad_norm': '0.5655', 'learning_rate': '0.0001685', 'entropy': '1.193', 'num_tokens': '1.81e+04', 'mean_token_accuracy': '0.6989', 'epoch': '0.1667'},
    {'loss': '1.338', 'grad_norm': '0.6059', 'learning_rate': '0.0001667', 'entropy': '1.281', 'num_tokens': '1.9e+04', 'mean_token_accuracy': '0.7052', 'epoch': '0.1759'},
    {'loss': '1.008', 'grad_norm': '0.4945', 'learning_rate': '0.0001648', 'entropy': '1.027', 'num_tokens': '2.002e+04', 'mean_token_accuracy': '0.7468', 'epoch': '0.1852'},
    {'loss': '1.198', 'grad_norm': '0.4842', 'learning_rate': '0.000163', 'entropy': '1.153', 'num_tokens': '2.105e+04', 'mean_token_accuracy': '0.7263', 'epoch': '0.1944'},
    {'loss': '1.291', 'grad_norm': '0.5345', 'learning_rate': '0.0001611', 'entropy': '1.368', 'num_tokens': '2.2e+04', 'mean_token_accuracy': '0.696', 'epoch': '0.2037'},
    {'loss': '1.189', 'grad_norm': '0.4933', 'learning_rate': '0.0001593', 'entropy': '1.203', 'num_tokens': '2.303e+04', 'mean_token_accuracy': '0.7155', 'epoch': '0.213'},
    {'loss': '1.119', 'grad_norm': '0.5787', 'learning_rate': '0.0001574', 'entropy': '1.178', 'num_tokens': '2.405e+04', 'mean_token_accuracy': '0.7302', 'epoch': '0.2222'},
    {'loss': '1.459', 'grad_norm': '0.5716', 'learning_rate': '0.0001556', 'entropy': '1.393', 'num_tokens': '2.507e+04', 'mean_token_accuracy': '0.6805', 'epoch': '0.2315'},
    {'loss': '1.301', 'grad_norm': '0.4937', 'learning_rate': '0.0001537', 'entropy': '1.318', 'num_tokens': '2.609e+04', 'mean_token_accuracy': '0.6968', 'epoch': '0.2407'},
    {'loss': '1.157', 'grad_norm': '0.5302', 'learning_rate': '0.0001519', 'entropy': '1.156', 'num_tokens': '2.695e+04', 'mean_token_accuracy': '0.7214', 'epoch': '0.25'},
    {'loss': '1.16', 'grad_norm': '0.4993', 'learning_rate': '0.00015', 'entropy': '1.154', 'num_tokens': '2.798e+04', 'mean_token_accuracy': '0.7195', 'epoch': '0.2593'},
    {'loss': '1.15', 'grad_norm': '0.4975', 'learning_rate': '0.0001481', 'entropy': '1.108', 'num_tokens': '2.9e+04', 'mean_token_accuracy': '0.7224', 'epoch': '0.2685'},
    {'loss': '1.118', 'grad_norm': '0.5401', 'learning_rate': '0.0001463', 'entropy': '1.136', 'num_tokens': '2.992e+04', 'mean_token_accuracy': '0.7312', 'epoch': '0.2778'},
    {'loss': '0.9493', 'grad_norm': '0.4902', 'learning_rate': '0.0001444', 'entropy': '0.9601', 'num_tokens': '3.089e+04', 'mean_token_accuracy': '0.7614', 'epoch': '0.287'},
    {'loss': '1.15', 'grad_norm': '0.5455', 'learning_rate': '0.0001426', 'entropy': '1.09', 'num_tokens': '3.191e+04', 'mean_token_accuracy': '0.7019', 'epoch': '0.2963'},
    {'loss': '1.199', 'grad_norm': '0.5619', 'learning_rate': '0.0001407', 'entropy': '1.19', 'num_tokens': '3.293e+04', 'mean_token_accuracy': '0.696', 'epoch': '0.3056'},
    {'loss': '1.193', 'grad_norm': '0.5112', 'learning_rate': '0.0001389', 'entropy': '1.15', 'num_tokens': '3.396e+04', 'mean_token_accuracy': '0.7253', 'epoch': '0.3148'},
    {'loss': '1.261', 'grad_norm': '0.6042', 'learning_rate': '0.000137', 'entropy': '1.177', 'num_tokens': '3.498e+04', 'mean_token_accuracy': '0.6989', 'epoch': '0.3241'},
    {'loss': '1.259', 'grad_norm': '0.5229', 'learning_rate': '0.0001352', 'entropy': '1.216', 'num_tokens': '3.601e+04', 'mean_token_accuracy': '0.695', 'epoch': '0.3333'},
    {'loss': '1.446', 'grad_norm': '0.5847', 'learning_rate': '0.0001333', 'entropy': '1.309', 'num_tokens': '3.694e+04', 'mean_token_accuracy': '0.6681', 'epoch': '0.3426'},
    {'loss': '1.179', 'grad_norm': '0.461', 'learning_rate': '0.0001315', 'entropy': '1.151', 'num_tokens': '3.796e+04', 'mean_token_accuracy': '0.7136', 'epoch': '0.3519'},
    {'loss': '1.259', 'grad_norm': '0.5563', 'learning_rate': '0.0001296', 'entropy': '1.178', 'num_tokens': '3.886e+04', 'mean_token_accuracy': '0.7297', 'epoch': '0.3611'},
    {'loss': '1.142', 'grad_norm': '0.5391', 'learning_rate': '0.0001278', 'entropy': '1.189', 'num_tokens': '3.977e+04', 'mean_token_accuracy': '0.7206', 'epoch': '0.3704'},
    {'loss': '1.257', 'grad_norm': '0.5589', 'learning_rate': '0.0001259', 'entropy': '1.269', 'num_tokens': '4.079e+04', 'mean_token_accuracy': '0.6921', 'epoch': '0.3796'},
    {'loss': '1.18', 'grad_norm': '0.4841', 'learning_rate': '0.0001241', 'entropy': '1.234', 'num_tokens': '4.177e+04', 'mean_token_accuracy': '0.7265', 'epoch': '0.3889'},
    {'loss': '1.11', 'grad_norm': '0.4714', 'learning_rate': '0.0001222', 'entropy': '1.148', 'num_tokens': '4.279e+04', 'mean_token_accuracy': '0.7301', 'epoch': '0.3981'},
    {'loss': '0.9641', 'grad_norm': '0.5133', 'learning_rate': '0.0001204', 'entropy': '0.9592', 'num_tokens': '4.367e+04', 'mean_token_accuracy': '0.7654', 'epoch': '0.4074'},
    {'loss': '0.9527', 'grad_norm': '0.4944', 'learning_rate': '0.0001185', 'entropy': '1.071', 'num_tokens': '4.47e+04', 'mean_token_accuracy': '0.7615', 'epoch': '0.4167'},
    {'loss': '1.074', 'grad_norm': '0.5555', 'learning_rate': '0.0001167', 'entropy': '1.135', 'num_tokens': '4.572e+04', 'mean_token_accuracy': '0.7292', 'epoch': '0.4259'},
    {'loss': '1.186', 'grad_norm': '0.4855', 'learning_rate': '0.0001148', 'entropy': '1.158', 'num_tokens': '4.674e+04', 'mean_token_accuracy': '0.7273', 'epoch': '0.4352'},
    {'loss': '1.385', 'grad_norm': '0.5351', 'learning_rate': '0.000113', 'entropy': '1.397', 'num_tokens': '4.777e+04', 'mean_token_accuracy': '0.6732', 'epoch': '0.4444'},
    {'loss': '1.167', 'grad_norm': '0.5289', 'learning_rate': '0.0001111', 'entropy': '1.213', 'num_tokens': '4.878e+04', 'mean_token_accuracy': '0.7031', 'epoch': '0.4537'},
    {'loss': '1.159', 'grad_norm': '0.5195', 'learning_rate': '0.0001093', 'entropy': '1.159', 'num_tokens': '4.98e+04', 'mean_token_accuracy': '0.7107', 'epoch': '0.463'},
    {'loss': '1.28', 'grad_norm': '0.5212', 'learning_rate': '0.0001074', 'entropy': '1.165', 'num_tokens': '5.082e+04', 'mean_token_accuracy': '0.7195', 'epoch': '0.4722'},
    {'loss': '1.042', 'grad_norm': '0.4678', 'learning_rate': '0.0001056', 'entropy': '1.056', 'num_tokens': '5.173e+04', 'mean_token_accuracy': '0.7434', 'epoch': '0.4815'},
    {'loss': '0.8308', 'grad_norm': '0.4865', 'learning_rate': '0.0001037', 'entropy': '0.8432', 'num_tokens': '5.265e+04', 'mean_token_accuracy': '0.7713', 'epoch': '0.4907'},
    {'loss': '1.252', 'grad_norm': '0.5528', 'learning_rate': '0.0001019', 'entropy': '1.225', 'num_tokens': '5.364e+04', 'mean_token_accuracy': '0.6964', 'epoch': '0.5'},
    {'loss': '1.169', 'grad_norm': '0.5218', 'learning_rate': '0.0001', 'entropy': '1.21', 'num_tokens': '5.464e+04', 'mean_token_accuracy': '0.7217', 'epoch': '0.5093'},
    {'loss': '0.9185', 'grad_norm': '0.5486', 'learning_rate': '9.815e-05', 'entropy': '0.9039', 'num_tokens': '5.555e+04', 'mean_token_accuracy': '0.7635', 'epoch': '0.5185'},
    {'loss': '1.14', 'grad_norm': '0.5456', 'learning_rate': '9.63e-05', 'entropy': '1.116', 'num_tokens': '5.653e+04', 'mean_token_accuracy': '0.725', 'epoch': '0.5278'},
    {'loss': '1.15', 'grad_norm': '0.5141', 'learning_rate': '9.444e-05', 'entropy': '1.172', 'num_tokens': '5.755e+04', 'mean_token_accuracy': '0.7146', 'epoch': '0.537'},
    {'loss': '1.261', 'grad_norm': '0.4818', 'learning_rate': '9.259e-05', 'entropy': '1.249', 'num_tokens': '5.857e+04', 'mean_token_accuracy': '0.7077', 'epoch': '0.5463'},
    {'loss': '1.12', 'grad_norm': '0.4639', 'learning_rate': '9.074e-05', 'entropy': '1.127', 'num_tokens': '5.958e+04', 'mean_token_accuracy': '0.742', 'epoch': '0.5556'},
    {'loss': '1.079', 'grad_norm': '0.4905', 'learning_rate': '8.889e-05', 'entropy': '1.101', 'num_tokens': '6.06e+04', 'mean_token_accuracy': '0.74', 'epoch': '0.5648'},
    {'loss': '1.104', 'grad_norm': '0.5304', 'learning_rate': '8.704e-05', 'entropy': '1.06', 'num_tokens': '6.151e+04', 'mean_token_accuracy': '0.7384', 'epoch': '0.5741'},
    {'loss': '1.276', 'grad_norm': '0.5344', 'learning_rate': '8.519e-05', 'entropy': '1.143', 'num_tokens': '6.245e+04', 'mean_token_accuracy': '0.7155', 'epoch': '0.5833'},
    {'loss': '0.9227', 'grad_norm': '0.4797', 'learning_rate': '8.333e-05', 'entropy': '0.9701', 'num_tokens': '6.347e+04', 'mean_token_accuracy': '0.7527', 'epoch': '0.5926'},
    {'loss': '1.215', 'grad_norm': '0.5136', 'learning_rate': '8.148e-05', 'entropy': '1.139', 'num_tokens': '6.45e+04', 'mean_token_accuracy': '0.7302', 'epoch': '0.6019'},
    {'loss': '1.041', 'grad_norm': '0.4537', 'learning_rate': '7.963e-05', 'entropy': '1.016', 'num_tokens': '6.552e+04', 'mean_token_accuracy': '0.738', 'epoch': '0.6111'},
    {'loss': '1.086', 'grad_norm': '0.4945', 'learning_rate': '7.778e-05', 'entropy': '1.078', 'num_tokens': '6.649e+04', 'mean_token_accuracy': '0.7272', 'epoch': '0.6204'},
    {'loss': '1.221', 'grad_norm': '0.4813', 'learning_rate': '7.593e-05', 'entropy': '1.197', 'num_tokens': '6.751e+04', 'mean_token_accuracy': '0.7107', 'epoch': '0.6296'},
    {'loss': '1.345', 'grad_norm': '0.4642', 'learning_rate': '7.407e-05', 'entropy': '1.313', 'num_tokens': '6.853e+04', 'mean_token_accuracy': '0.6872', 'epoch': '0.6389'},
    {'loss': '1.198', 'grad_norm': '0.4595', 'learning_rate': '7.222e-05', 'entropy': '1.169', 'num_tokens': '6.956e+04', 'mean_token_accuracy': '0.7136', 'epoch': '0.6481'},
    {'loss': '1.415', 'grad_norm': '0.4894', 'learning_rate': '7.037e-05', 'entropy': '1.334', 'num_tokens': '7.058e+04', 'mean_token_accuracy': '0.6667', 'epoch': '0.6574'},
    {'loss': '1.369', 'grad_norm': '0.4845', 'learning_rate': '6.852e-05', 'entropy': '1.298', 'num_tokens': '7.161e+04', 'mean_token_accuracy': '0.6862', 'epoch': '0.6667'},
    {'loss': '1.244', 'grad_norm': '0.4773', 'learning_rate': '6.667e-05', 'entropy': '1.214', 'num_tokens': '7.263e+04', 'mean_token_accuracy': '0.695', 'epoch': '0.6759'},
    {'loss': '0.9448', 'grad_norm': '0.4576', 'learning_rate': '6.481e-05', 'entropy': '0.9694', 'num_tokens': '7.354e+04', 'mean_token_accuracy': '0.7582', 'epoch': '0.6852'},
    {'loss': '1.177', 'grad_norm': '0.4707', 'learning_rate': '6.296e-05', 'entropy': '1.175', 'num_tokens': '7.453e+04', 'mean_token_accuracy': '0.7169', 'epoch': '0.6944'},
    {'loss': '1.269', 'grad_norm': '0.5095', 'learning_rate': '6.111e-05', 'entropy': '1.207', 'num_tokens': '7.555e+04', 'mean_token_accuracy': '0.7097', 'epoch': '0.7037'},
    {'loss': '1.116', 'grad_norm': '0.5043', 'learning_rate': '5.926e-05', 'entropy': '1.152', 'num_tokens': '7.656e+04', 'mean_token_accuracy': '0.7234', 'epoch': '0.713'},
    {'loss': '1.041', 'grad_norm': '0.527', 'learning_rate': '5.741e-05', 'entropy': '1.039', 'num_tokens': '7.756e+04', 'mean_token_accuracy': '0.7645', 'epoch': '0.7222'},
    {'loss': '1.135', 'grad_norm': '0.4752', 'learning_rate': '5.556e-05', 'entropy': '1.185', 'num_tokens': '7.858e+04', 'mean_token_accuracy': '0.7322', 'epoch': '0.7315'},
    {'loss': '1.076', 'grad_norm': '0.4992', 'learning_rate': '5.37e-05', 'entropy': '1.107', 'num_tokens': '7.96e+04', 'mean_token_accuracy': '0.7234', 'epoch': '0.7407'},
    {'loss': '1.203', 'grad_norm': '0.4971', 'learning_rate': '5.185e-05', 'entropy': '1.204', 'num_tokens': '8.061e+04', 'mean_token_accuracy': '0.7156', 'epoch': '0.75'},
    {'loss': '1.019', 'grad_norm': '0.4483', 'learning_rate': '5e-05', 'entropy': '1.049', 'num_tokens': '8.162e+04', 'mean_token_accuracy': '0.7394', 'epoch': '0.7593'},
    {'loss': '1.388', 'grad_norm': '0.5738', 'learning_rate': '4.815e-05', 'entropy': '1.244', 'num_tokens': '8.256e+04', 'mean_token_accuracy': '0.682', 'epoch': '0.7685'},
    {'loss': '0.918', 'grad_norm': '0.4923', 'learning_rate': '4.63e-05', 'entropy': '0.9929', 'num_tokens': '8.354e+04', 'mean_token_accuracy': '0.7474', 'epoch': '0.7778'},
    {'loss': '1.45', 'grad_norm': '0.5221', 'learning_rate': '4.444e-05', 'entropy': '1.361', 'num_tokens': '8.456e+04', 'mean_token_accuracy': '0.6921', 'epoch': '0.787'},
    {'loss': '1.177', 'grad_norm': '0.4975', 'learning_rate': '4.259e-05', 'entropy': '1.232', 'num_tokens': '8.552e+04', 'mean_token_accuracy': '0.6999', 'epoch': '0.7963'},
    {'loss': '1.154', 'grad_norm': '0.518', 'learning_rate': '4.074e-05', 'entropy': '1.159', 'num_tokens': '8.644e+04', 'mean_token_accuracy': '0.7394', 'epoch': '0.8056'},
    {'loss': '1.224', 'grad_norm': '0.4508', 'learning_rate': '3.889e-05', 'entropy': '1.255', 'num_tokens': '8.746e+04', 'mean_token_accuracy': '0.7097', 'epoch': '0.8148'},
    {'loss': '1.153', 'grad_norm': '0.5173', 'learning_rate': '3.704e-05', 'entropy': '1.161', 'num_tokens': '8.848e+04', 'mean_token_accuracy': '0.7126', 'epoch': '0.8241'},
    {'loss': '1.11', 'grad_norm': '0.4561', 'learning_rate': '3.519e-05', 'entropy': '1.16', 'num_tokens': '8.949e+04', 'mean_token_accuracy': '0.7198', 'epoch': '0.8333'},
    {'loss': '1.048', 'grad_norm': '0.4583', 'learning_rate': '3.333e-05', 'entropy': '0.9991', 'num_tokens': '9.052e+04', 'mean_token_accuracy': '0.7556', 'epoch': '0.8426'},
    {'loss': '1.134', 'grad_norm': '0.4828', 'learning_rate': '3.148e-05', 'entropy': '1.126', 'num_tokens': '9.154e+04', 'mean_token_accuracy': '0.7302', 'epoch': '0.8519'},
    {'loss': '1.256', 'grad_norm': '0.508', 'learning_rate': '2.963e-05', 'entropy': '1.225', 'num_tokens': '9.257e+04', 'mean_token_accuracy': '0.7136', 'epoch': '0.8611'},
    {'loss': '1.435', 'grad_norm': '0.53', 'learning_rate': '2.778e-05', 'entropy': '1.36', 'num_tokens': '9.358e+04', 'mean_token_accuracy': '0.6699', 'epoch': '0.8704'},
    {'loss': '1.379', 'grad_norm': '0.5112', 'learning_rate': '2.593e-05', 'entropy': '1.27', 'num_tokens': '9.461e+04', 'mean_token_accuracy': '0.6862', 'epoch': '0.8796'},
    {'loss': '1.222', 'grad_norm': '0.4698', 'learning_rate': '2.407e-05', 'entropy': '1.19', 'num_tokens': '9.561e+04', 'mean_token_accuracy': '0.6954', 'epoch': '0.8889'},
    {'loss': '1.238', 'grad_norm': '0.4559', 'learning_rate': '2.222e-05', 'entropy': '1.233', 'num_tokens': '9.663e+04', 'mean_token_accuracy': '0.7126', 'epoch': '0.8981'},
    {'loss': '1.105', 'grad_norm': '0.7178', 'learning_rate': '2.037e-05', 'entropy': '1.118', 'num_tokens': '9.766e+04', 'mean_token_accuracy': '0.7263', 'epoch': '0.9074'},
    {'loss': '1.063', 'grad_norm': '0.4801', 'learning_rate': '1.852e-05', 'entropy': '1.067', 'num_tokens': '9.854e+04', 'mean_token_accuracy': '0.7565', 'epoch': '0.9167'},
    {'loss': '1.176', 'grad_norm': '0.4464', 'learning_rate': '1.667e-05', 'entropy': '1.133', 'num_tokens': '9.956e+04', 'mean_token_accuracy': '0.738', 'epoch': '0.9259'},
    {'loss': '0.9766', 'grad_norm': '0.4784', 'learning_rate': '1.481e-05', 'entropy': '1.027', 'num_tokens': '1.005e+05', 'mean_token_accuracy': '0.7594', 'epoch': '0.9352'},
    {'loss': '1.152', 'grad_norm': '0.4909', 'learning_rate': '1.296e-05', 'entropy': '1.189', 'num_tokens': '1.015e+05', 'mean_token_accuracy': '0.7263', 'epoch': '0.9444'},
    {'loss': '0.9983', 'grad_norm': '0.4601', 'learning_rate': '1.111e-05', 'entropy': '1.001', 'num_tokens': '1.025e+05', 'mean_token_accuracy': '0.7737', 'epoch': '0.9537'},
    {'loss': '1.175', 'grad_norm': '0.4791', 'learning_rate': '9.259e-06', 'entropy': '1.158', 'num_tokens': '1.035e+05', 'mean_token_accuracy': '0.7234', 'epoch': '0.963'},
    {'loss': '1.088', 'grad_norm': '0.5085', 'learning_rate': '7.407e-06', 'entropy': '1.093', 'num_tokens': '1.046e+05', 'mean_token_accuracy': '0.7341', 'epoch': '0.9722'},
    {'loss': '1.055', 'grad_norm': '0.5007', 'learning_rate': '5.556e-06', 'entropy': '1.075', 'num_tokens': '1.055e+05', 'mean_token_accuracy': '0.741', 'epoch': '0.9815'},
    {'loss': '1.127', 'grad_norm': '0.5613', 'learning_rate': '3.704e-06', 'entropy': '1.197', 'num_tokens': '1.065e+05', 'mean_token_accuracy': '0.7243', 'epoch': '0.9907'},
    {'loss': '1.319', 'grad_norm': '0.4822', 'learning_rate': '1.852e-06', 'entropy': '1.279', 'num_tokens': '1.076e+05', 'mean_token_accuracy': '0.6804', 'epoch': '1'},
]

base_time = time.time() - 17670  # run started ~4:54:30 ago
records = []

# train_begin
records.append({
    "type": "train_begin",
    "max_steps": 108,
    "num_epochs": 1,
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "wall_time": base_time,
})

# per-step metrics
total_steps = len(RAW_STEPS)
for i, s in enumerate(RAW_STEPS):
    step = i + 1
    elapsed = (step / total_steps) * 17670
    records.append({
        "type":                "metric",
        "step":                step,
        "max_steps":           108,
        "epoch":               float(s["epoch"]),
        "loss":                float(s["loss"]),
        "grad_norm":           float(s["grad_norm"]),
        "learning_rate":       float(s["learning_rate"]),
        "mean_token_accuracy": float(s["mean_token_accuracy"]),
        "entropy":             float(s["entropy"]),
        "elapsed_s":           round(elapsed),
        "eta_s":               0,
        "wall_time":           base_time + elapsed,
    })

# epoch_end
records.append({
    "type": "epoch_end",
    "epoch": 1.0,
    "step": 108,
    "wall_time": base_time + 17670,
})

# train_end
records.append({
    "type": "train_end",
    "step": 108,
    "elapsed_s": 17670,
    "wall_time": base_time + 17670,
})

with open(OUT, "w", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"Wrote {len(records)} records to {OUT}")
print(f"  Steps: {total_steps}")
print(f"  Loss: {float(RAW_STEPS[0]['loss']):.3f} -> {float(RAW_STEPS[-1]['loss']):.3f}")
print(f"  Accuracy: {float(RAW_STEPS[0]['mean_token_accuracy']):.3f} -> {float(RAW_STEPS[-1]['mean_token_accuracy']):.3f}")
