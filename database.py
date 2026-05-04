import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, BigInteger, Text, update, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

os.makedirs("database", exist_ok=True)
DATABASE_URL = "sqlite:///database/vpn_bot.db"
engine = create_engine(DATABASE_URL, echo=False)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    trial_used = Column(Boolean, default=False)

    def full_name(self):
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.username or str(self.id)

class Tariff(Base):
    __tablename__ = 'tariffs'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    days = Column(Integer, nullable=False)
    traffic_gb = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

class Subscription(Base):
    __tablename__ = 'subscriptions'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    tariff_id = Column(Integer, nullable=False)
    vpn_config = Column(Text, nullable=True)
    vpn_uuid = Column(String, nullable=True)
    start_date = Column(DateTime, default=datetime.now)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    auto_renew = Column(Boolean, default=False)
    traffic_used = Column(BigInteger, default=0)

    def days_left(self):
        delta = self.end_date - datetime.now()
        return max(0, delta.days)

    def is_expired(self):
        return datetime.now() > self.end_date

class Payment(Base):
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    amount = Column(Integer, nullable=False)
    tariff_id = Column(Integer, nullable=False)
    payment_system = Column(String)
    status = Column(String, default='pending')
    created_at = Column(DateTime, default=datetime.now)
    paid_at = Column(DateTime, nullable=True)
    external_id = Column(String, nullable=True)

class Database:
    def __init__(self):
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)

    def get_session(self):
        return self.SessionLocal()

    def add_user(self, tg_id, username=None, first_name=None, last_name=None):
        session = self.get_session()
        try:
            user = session.query(User).filter(User.id == tg_id).first()
            if not user:
                user = User(id=tg_id, username=username, first_name=first_name, last_name=last_name)
                session.add(user)
                session.commit()
                session.refresh(user)
            return user
        finally:
            session.close()

    def get_user(self, tg_id):
        session = self.get_session()
        try:
            return session.query(User).filter(User.id == tg_id).first()
        finally:
            session.close()

    def is_admin(self, tg_id):
        user = self.get_user(tg_id)
        return user and user.is_admin

    def set_admin(self, tg_id, is_admin=True):
        session = self.get_session()
        try:
            user = session.query(User).filter(User.id == tg_id).first()
            if user:
                user.is_admin = is_admin
                session.commit()
        finally:
            session.close()

    def use_trial(self, tg_id):
        session = self.get_session()
        try:
            user = session.query(User).filter(User.id == tg_id).first()
            if user:
                user.trial_used = True
                session.commit()
        finally:
            session.close()

    def has_trial_used(self, tg_id):
        user = self.get_user(tg_id)
        return user and user.trial_used

    def add_tariff(self, name, price, days, traffic_gb=None, sort_order=0):
        session = self.get_session()
        try:
            tariff = Tariff(name=name, price=price, days=days, traffic_gb=traffic_gb, sort_order=sort_order)
            session.add(tariff)
            session.commit()
            return tariff
        finally:
            session.close()

    def get_all_tariffs(self, active_only=True):
        session = self.get_session()
        try:
            query = session.query(Tariff)
            if active_only:
                query = query.filter(Tariff.is_active == True)
            return query.order_by(Tariff.sort_order).all()
        finally:
            session.close()

    def get_tariff(self, tariff_id):
        session = self.get_session()
        try:
            return session.query(Tariff).filter(Tariff.id == tariff_id).first()
        finally:
            session.close()

    def get_active_subscription(self, user_id):
        session = self.get_session()
        try:
            return session.query(Subscription).filter(
                Subscription.user_id == user_id,
                Subscription.is_active == True,
                Subscription.end_date > datetime.now()
            ).first()
        finally:
            session.close()

    def create_subscription(self, user_id, tariff_id, vpn_config=None, vpn_uuid=None):
        session = self.get_session()
        try:
            tariff = self.get_tariff(tariff_id)
            if not tariff:
                return None
            old = session.query(Subscription).filter(
                Subscription.user_id == user_id,
                Subscription.is_active == True
            ).all()
            for sub in old:
                sub.is_active = False
            sub = Subscription(
                user_id=user_id,
                tariff_id=tariff_id,
                vpn_config=vpn_config,
                vpn_uuid=vpn_uuid,
                end_date=datetime.now() + timedelta(days=tariff.days)
            )
            session.add(sub)
            session.commit()
            session.refresh(sub)
            return sub
        finally:
            session.close()

    def cancel_subscription(self, sub_id):
        session = self.get_session()
        try:
            sub = session.query(Subscription).filter(Subscription.id == sub_id).first()
            if sub:
                sub.is_active = False
                session.commit()
        finally:
            session.close()

    def create_payment(self, user_id, amount, tariff_id, payment_system='test'):
        session = self.get_session()
        try:
            payment = Payment(user_id=user_id, amount=amount, tariff_id=tariff_id, payment_system=payment_system)
            session.add(payment)
            session.commit()
            return payment
        finally:
            session.close()

    def confirm_payment(self, payment_id, external_id=None):
        session = self.get_session()
        try:
            payment = session.query(Payment).filter(Payment.id == payment_id).first()
            if payment:
                payment.status = 'success'
                payment.paid_at = datetime.now()
                if external_id:
                    payment.external_id = external_id
                session.commit()
            return payment
        finally:
            session.close()

    def get_total_earnings(self):
        session = self.get_session()
        try:
            total = session.query(func.sum(Payment.amount)).filter(Payment.status == 'success').scalar()
            return total or 0
        finally:
            session.close()

    def get_stats(self):
        session = self.get_session()
        try:
            total_users = session.query(User).count()
            active = session.query(Subscription).filter(
                Subscription.is_active == True,
                Subscription.end_date > datetime.now()
            ).count()
            return {'total_users': total_users, 'active_subscriptions': active, 'total_earnings': self.get_total_earnings()}
        finally:
            session.close()

    def get_all_users(self, limit=100, offset=0):
        session = self.get_session()
        try:
            return session.query(User).order_by(User.created_at.desc()).limit(limit).offset(offset).all()
        finally:
            session.close()

    def get_total_users_count(self):
        session = self.get_session()
        try:
            return session.query(User).count()
        finally:
            session.close()

    def get_active_subscriptions_count(self):
        session = self.get_session()
        try:
            return session.query(Subscription).filter(
                Subscription.is_active == True,
                Subscription.end_date > datetime.now()
            ).count()
        finally:
            session.close()

    def update_tariff_price(self, tariff_id, new_price):
        session = self.get_session()
        try:
            session.execute(update(Tariff).where(Tariff.id == tariff_id).values(price=new_price))
            session.commit()
        finally:
            session.close()

    def update_tariff_name(self, tariff_id, new_name):
        session = self.get_session()
        try:
            session.execute(update(Tariff).where(Tariff.id == tariff_id).values(name=new_name))
            session.commit()
        finally:
            session.close()

    def add_new_tariff(self, name, price, days, traffic_gb=None, sort_order=None):
        session = self.get_session()
        try:
            max_order = session.query(func.max(Tariff.sort_order)).scalar() or 0
            tariff = Tariff(
                name=name,
                price=price,
                days=days,
                traffic_gb=traffic_gb,
                sort_order=sort_order or (max_order + 1)
            )
            session.add(tariff)
            session.commit()
            return tariff
        finally:
            session.close()

    def delete_tariff(self, tariff_id):
        session = self.get_session()
        try:
            tariff = session.query(Tariff).filter(Tariff.id == tariff_id).first()
            if tariff:
                session.delete(tariff)
                session.commit()
                return True
            return False
        finally:
            session.close()

    def toggle_user_block(self, user_id):
        session = self.get_session()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if user:
                user.is_banned = not user.is_banned
                session.commit()
                return user.is_banned
            return None
        finally:
            session.close()

    def get_user_by_username(self, username):
        session = self.get_session()
        try:
            return session.query(User).filter(User.username == username.lstrip('@')).first()
        finally:
            session.close()

db = Database()

def init_tariffs():
    session = db.get_session()
    try:
        if session.query(Tariff).count() == 0:
            tariffs = [
                {"name": "Пробный период 3 дня", "price": 0, "days": 3, "traffic_gb": 10, "sort_order": 0},
                {"name": "1 месяц", "price": 100, "days": 30, "traffic_gb": None, "sort_order": 1},
                {"name": "3 месяца", "price": 250, "days": 90, "traffic_gb": None, "sort_order": 2},
                {"name": "6 месяцев", "price": 480, "days": 180, "traffic_gb": None, "sort_order": 3},
                {"name": "12 месяцев", "price": 940, "days": 365, "traffic_gb": None, "sort_order": 4},
            ]
            for t in tariffs:
                session.add(Tariff(**t))
            session.commit()
    finally:
        session.close()

init_tariffs()
print("База данных готова!")