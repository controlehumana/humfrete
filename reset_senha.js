// Reset manual de senha de qualquer usuário do Firebase Auth (workaround enquanto
// o painel Admin não pode trocar senha de terceiros — ver CLAUDE.md).
// Requer: npm install firebase-admin (uma vez, na pasta Frete/)
// Uso: node reset_senha.js <email> <novaSenha>
const { initializeApp, cert } = require('firebase-admin/app');
const { getAuth } = require('firebase-admin/auth');

const serviceAccount = require('./serviceAccountKey.json');
initializeApp({ credential: cert(serviceAccount) });

const [, , email, newPassword] = process.argv;
if (!email || !newPassword || newPassword.length < 6) {
  console.error('Uso: node reset_senha.js <email> <novaSenha (min. 6 caracteres)>');
  process.exit(1);
}

getAuth().getUserByEmail(email)
  .then(user => getAuth().updateUser(user.uid, { password: newPassword }))
  .then(user => {
    console.log('OK - senha atualizada para', user.email, '(uid:', user.uid + ')');
    process.exit(0);
  })
  .catch(err => {
    console.error('ERRO:', err.code || err.message);
    process.exit(1);
  });
