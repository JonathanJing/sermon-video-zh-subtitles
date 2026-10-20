export function firestoreStore(db) {
  return {
    transaction(callback) {
      return db.runTransaction(async (transaction) => callback({
        async get(path) {
          const snapshot = await transaction.get(db.doc(path));
          return snapshot.exists ? snapshot.data() : null;
        },
        set(path, value) { transaction.set(db.doc(path), value); },
        delete(path) { transaction.delete(db.doc(path)); },
      }));
    },
  };
}
