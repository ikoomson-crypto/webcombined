# acctsys/forms.py – Complete version

from flask_wtf import FlaskForm
from wtforms import Form, StringField, PasswordField, SubmitField, FloatField, DateField, SelectField, TextAreaField, BooleanField, IntegerField, DecimalField
from wtforms.validators import DataRequired, EqualTo, Length, ValidationError
from datetime import datetime
from wtforms import FieldList, FormField
from flask_wtf.file import FileField, FileAllowed, FileRequired
from acctsys.models import User, ChartOfAccount, Supplier, Customer, Invoice, InvoiceLine, AccountType
from extensions import db


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Username already taken.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email already registered.')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')


# ==================== INVOICE LINE FORM (plain Form) ====================
class InvoiceLineForm(Form):
    description = StringField('Description', validators=[DataRequired()])
    quantity = FloatField('Qty', validators=[DataRequired()], default=1.0)
    unit_price = FloatField('Unit Price', validators=[DataRequired()])
    account_id = SelectField('Account', coerce=int, validators=[DataRequired()])


# ==================== INVOICE FORMS ====================
class InvoiceForm(FlaskForm):
    invoice_number = StringField('Invoice Number', validators=[DataRequired()])
    customer_id = SelectField('Customer', choices=[], coerce=int, validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    status = SelectField('Status', choices=[('Paid', 'Paid'), ('Pending', 'Pending'), ('Overdue', 'Overdue')])
    description = TextAreaField('Description')
    lines = FieldList(FormField(InvoiceLineForm), min_entries=1)
    submit = SubmitField('Add Invoice')


class InvoiceEditForm(FlaskForm):
    invoice_number = StringField('Invoice Number', validators=[DataRequired()])
    customer_id = SelectField('Customer', choices=[], coerce=int, validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    status = SelectField('Status', choices=[('Paid', 'Paid'), ('Pending', 'Pending'), ('Overdue', 'Overdue')])
    description = TextAreaField('Description')
    lines = FieldList(FormField(InvoiceLineForm), min_entries=1)
    submit = SubmitField('Update Invoice')

    original_invoice_number = None

    def validate_invoice_number(self, invoice_number):
        if self.original_invoice_number and self.original_invoice_number == invoice_number.data:
            return
        invoice = Invoice.query.filter_by(invoice_number=invoice_number.data).first()
        if invoice:
            raise ValidationError('Invoice number already exists.')


# ==================== PURCHASE LINE FORM (plain Form) ====================
class PurchaseLineForm(Form):
    description = StringField('Description', validators=[DataRequired()])
    quantity = FloatField('Qty', validators=[DataRequired()], default=1.0)
    unit_price = FloatField('Unit Price', validators=[DataRequired()])
    account_id = SelectField('Account', coerce=int, validators=[DataRequired()])


# ==================== PURCHASE FORMS ====================
class PurchaseForm(FlaskForm):
    purchase_number = StringField('Purchase Number', validators=[DataRequired()])
    supplier_id = SelectField('Supplier', choices=[], coerce=int, validators=[DataRequired()])
    invoice_number = StringField('Invoice Number')
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    due_date = DateField('Due Date')
    status = SelectField('Status', choices=[
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
        ('Overdue', 'Overdue')
    ])
    description = TextAreaField('Description')

    lines = FieldList(FormField(PurchaseLineForm), min_entries=0)

    submit = SubmitField('Save Purchase')


class PurchaseEditForm(FlaskForm):
    purchase_number = StringField('Purchase Number', validators=[DataRequired()])
    supplier_id = SelectField('Supplier', choices=[], coerce=int, validators=[DataRequired()])
    invoice_number = StringField('Invoice Number')
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    due_date = DateField('Due Date')
    status = SelectField('Status', choices=[
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
        ('Overdue', 'Overdue')
    ])
    description = TextAreaField('Description')

    lines = FieldList(FormField(PurchaseLineForm), min_entries=0)

    submit = SubmitField('Update Purchase')


# ==================== EXPENSE FORM ====================
class ExpenseForm(FlaskForm):
    description = StringField('Description', validators=[DataRequired()])
    amount = FloatField('Amount', validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    payment_method = SelectField('Payment Method', choices=[('Cash', 'Cash'), ('Credit Card', 'Credit Card'),
                                                            ('Bank Transfer', 'Bank Transfer')])
    category = SelectField('Category', choices=[], coerce=int)
    submit = SubmitField('Add Expense')


# ==================== ACCOUNT TYPE FORMS ====================
class AccountTypeForm(FlaskForm):
    name = StringField('Account Type Name', validators=[DataRequired(), Length(max=50)])
    description = TextAreaField('Description')
    normal_balance = SelectField('Normal Balance', choices=[('Debit', 'Debit'), ('Credit', 'Credit')])
    min_code = IntegerField('Minimum Code', validators=[DataRequired()])
    max_code = IntegerField('Maximum Code', validators=[DataRequired()])
    submit = SubmitField('Add Account Type')

    def validate_name(self, name):
        account_type = AccountType.query.filter_by(name=name.data).first()
        if account_type:
            raise ValidationError('Account type name already exists.')

    def validate_min_code(self, min_code):
        if min_code.data <= 0:
            raise ValidationError('Minimum code must be greater than 0.')
        if self.max_code.data and min_code.data >= self.max_code.data:
            raise ValidationError('Minimum code must be less than maximum code.')

    def validate_max_code(self, max_code):
        if max_code.data <= 0:
            raise ValidationError('Maximum code must be greater than 0.')
        if self.min_code.data and max_code.data <= self.min_code.data:
            raise ValidationError('Maximum code must be greater than minimum code.')


class AccountTypeEditForm(FlaskForm):
    name = StringField('Account Type Name', validators=[DataRequired(), Length(max=50)])
    description = TextAreaField('Description')
    normal_balance = SelectField('Normal Balance', choices=[('Debit', 'Debit'), ('Credit', 'Credit')])
    min_code = IntegerField('Minimum Code', validators=[DataRequired()])
    max_code = IntegerField('Maximum Code', validators=[DataRequired()])
    submit = SubmitField('Update Account Type')

    original_name = None

    def validate_name(self, name):
        if self.original_name and self.original_name == name.data:
            return
        account_type = AccountType.query.filter_by(name=name.data).first()
        if account_type:
            raise ValidationError('Account type name already exists.')

    def validate_min_code(self, min_code):
        if min_code.data <= 0:
            raise ValidationError('Minimum code must be greater than 0.')
        if self.max_code.data and min_code.data >= self.max_code.data:
            raise ValidationError('Minimum code must be less than maximum code.')

    def validate_max_code(self, max_code):
        if max_code.data <= 0:
            raise ValidationError('Maximum code must be greater than 0.')
        if self.min_code.data and max_code.data <= self.min_code.data:
            raise ValidationError('Maximum code must be greater than minimum code.')


# ==================== CHART OF ACCOUNT FORMS ====================
class ChartOfAccountForm(FlaskForm):
    account_code = StringField('Account Code', validators=[Length(max=20)])
    account_name = StringField('Account Name', validators=[DataRequired(), Length(max=100)])
    account_type_id = SelectField('Account Type', choices=[], coerce=int, validators=[DataRequired()])
    description = TextAreaField('Description')
    opening_balance = FloatField('Opening Balance', default=0.0)
    parent_id = SelectField('Parent Account', choices=[], coerce=int, default=0)
    is_main_account = BooleanField('This is a Main Account (Parent)')
    submit = SubmitField('Add Account')

    def validate_account_code(self, account_code):
        if account_code.data and account_code.data.strip():
            account = ChartOfAccount.query.filter_by(account_code=account_code.data).first()
            if account:
                raise ValidationError('Account code already exists.')


class ChartOfAccountEditForm(FlaskForm):
    account_code = StringField('Account Code', validators=[DataRequired(), Length(max=20)])
    account_name = StringField('Account Name', validators=[DataRequired(), Length(max=100)])
    account_type_id = SelectField('Account Type', choices=[], coerce=int)
    description = TextAreaField('Description')
    balance = FloatField('Balance', default=0.0)
    parent_id = SelectField('Parent Account', choices=[], coerce=int, default=0)
    is_main_account = BooleanField('This is a Main Account (Parent)')
    is_active = BooleanField('Active')
    submit = SubmitField('Update Account')


# ==================== SUPPLIER FORMS ====================
class SupplierForm(FlaskForm):
    name = StringField('Company Name', validators=[DataRequired(), Length(max=100)])
    contact_person = StringField('Contact Person', validators=[Length(max=100)])
    email = StringField('Email', validators=[DataRequired()])
    phone = StringField('Phone', validators=[Length(max=20)])
    address = TextAreaField('Address')
    tax_id = StringField('Tax ID/VAT Number', validators=[Length(max=50)])
    payment_terms = SelectField('Payment Terms', choices=[
        ('Net 15', 'Net 15'),
        ('Net 30', 'Net 30'),
        ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'),
        ('Cash on Delivery', 'Cash on Delivery')
    ])
    opening_balance = FloatField('Opening Balance', default=0.0)
    submit = SubmitField('Add Supplier')


class SupplierEditForm(FlaskForm):
    name = StringField('Company Name', validators=[DataRequired(), Length(max=100)])
    contact_person = StringField('Contact Person', validators=[Length(max=100)])
    email = StringField('Email', validators=[DataRequired()])
    phone = StringField('Phone', validators=[Length(max=20)])
    address = TextAreaField('Address')
    tax_id = StringField('Tax ID/VAT Number', validators=[Length(max=50)])
    payment_terms = SelectField('Payment Terms', choices=[
        ('Net 15', 'Net 15'),
        ('Net 30', 'Net 30'),
        ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'),
        ('Cash on Delivery', 'Cash on Delivery')
    ])
    opening_balance = FloatField('Opening Balance', default=0.0)
    current_balance = FloatField('Current Balance', default=0.0)
    is_active = BooleanField('Active')
    submit = SubmitField('Update Supplier')


# ==================== CUSTOMER FORMS ====================
class CustomerForm(FlaskForm):
    name = StringField('Company/Person Name', validators=[DataRequired(), Length(max=100)])
    contact_person = StringField('Contact Person', validators=[Length(max=100)])
    email = StringField('Email', validators=[DataRequired()])
    phone = StringField('Phone', validators=[Length(max=20)])
    address = TextAreaField('Address')
    tax_id = StringField('Tax ID/VAT Number', validators=[Length(max=50)])
    credit_limit = FloatField('Credit Limit', default=0.0)
    opening_balance = FloatField('Opening Balance', default=0.0)
    payment_terms = SelectField('Payment Terms', choices=[
        ('Net 15', 'Net 15'),
        ('Net 30', 'Net 30'),
        ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'),
        ('Due on Receipt', 'Due on Receipt')
    ])
    submit = SubmitField('Add Customer')


class CustomerEditForm(FlaskForm):
    name = StringField('Company/Person Name', validators=[DataRequired(), Length(max=100)])
    contact_person = StringField('Contact Person', validators=[Length(max=100)])
    email = StringField('Email', validators=[DataRequired()])
    phone = StringField('Phone', validators=[Length(max=20)])
    address = TextAreaField('Address')
    tax_id = StringField('Tax ID/VAT Number', validators=[Length(max=50)])
    credit_limit = FloatField('Credit Limit', default=0.0)
    opening_balance = FloatField('Opening Balance', default=0.0)
    current_balance = FloatField('Current Balance', default=0.0)
    payment_terms = SelectField('Payment Terms', choices=[
        ('Net 15', 'Net 15'),
        ('Net 30', 'Net 30'),
        ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'),
        ('Due on Receipt', 'Due on Receipt')
    ])
    is_active = BooleanField('Active')
    submit = SubmitField('Update Customer')


# ==================== PAYMENT VOUCHER FORMS ====================
class PaymentVoucherForm(FlaskForm):
    supplier_id = SelectField('Supplier', choices=[], coerce=int, validators=[DataRequired()])
    currency = SelectField('Currency', choices=[
        ('USD', 'USD - US Dollar'),
        ('EUR', 'EUR - Euro'),
        ('GBP', 'GBP - British Pound'),
        ('GHS', 'GHS - Ghana Cedi'),
        ('NGN', 'NGN - Nigerian Naira')
    ], default='USD')
    exchange_rate = FloatField('Exchange Rate', default=1.0, validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    description = TextAreaField('Description', validators=[DataRequired()])
    payment_account_id = SelectField('Payment Account (Cash/Bank)', choices=[], coerce=int, validators=[DataRequired()])
    wht_rate = FloatField('WHT Rate (%)', default=0.0)
    vat_rate = FloatField('VAT Rate (%)', default=0.0)
    gross_amount = FloatField('Gross Amount', validators=[DataRequired()])
    reference_number = StringField('Reference #')
    attachment = FileField('Support Document', validators=[
        FileAllowed(['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'], 'PDF, JPG, PNG, DOC only!')])
    submit = SubmitField('Save Payment Voucher')

    def validate_gross_amount(self, gross_amount):
        if gross_amount.data <= 0:
            raise ValidationError('Gross amount must be greater than 0')


class PaymentVoucherEditForm(FlaskForm):
    supplier_id = SelectField('Supplier', choices=[], coerce=int, validators=[DataRequired()])
    currency = SelectField('Currency', choices=[
        ('USD', 'USD - US Dollar'),
        ('EUR', 'EUR - Euro'),
        ('GBP', 'GBP - British Pound'),
        ('GHS', 'GHS - Ghana Cedi'),
        ('NGN', 'NGN - Nigerian Naira')
    ], default='USD')
    exchange_rate = FloatField('Exchange Rate', default=1.0, validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    description = TextAreaField('Description', validators=[DataRequired()])
    payment_account_id = SelectField('Payment Account (Cash/Bank)', choices=[], coerce=int, validators=[DataRequired()])
    wht_rate = FloatField('WHT Rate (%)', default=0.0)
    vat_rate = FloatField('VAT Rate (%)', default=0.0)
    gross_amount = FloatField('Gross Amount', validators=[DataRequired()])
    reference_number = StringField('Reference #')
    submit = SubmitField('Update Payment Voucher')

    def validate_gross_amount(self, gross_amount):
        if gross_amount.data <= 0:
            raise ValidationError('Gross amount must be greater than 0')


# ==================== JOURNAL ENTRY FORMS ====================
class JournalEntryForm(FlaskForm):
    entry_number = StringField('Journal Entry #', validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    description = TextAreaField('Description', validators=[DataRequired()])
    account_id = SelectField('Account', choices=[], coerce=int)
    debit = FloatField('Debit Amount', default=0.0)
    credit = FloatField('Credit Amount', default=0.0)
    submit = SubmitField('Add Journal Entry')

    def validate_debit_credit(self):
        if self.debit.data > 0 and self.credit.data > 0:
            raise ValidationError('Cannot have both debit and credit amounts')
        if self.debit.data == 0 and self.credit.data == 0:
            raise ValidationError('Either debit or credit amount must be greater than 0')
        return True


class JournalLineForm(Form):
    account_id = SelectField('Account', coerce=int)
    debit = FloatField('Debit', default=0.0)
    credit = FloatField('Credit', default=0.0)


class MultiJournalEntryForm(FlaskForm):
    entry_number = StringField('Journal Entry #', validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    description = TextAreaField('Description', validators=[DataRequired()])
    lines = FieldList(FormField(JournalLineForm), min_entries=2, max_entries=10)
    submit = SubmitField('Save Journal Entry')


class JournalEntryFormNew(FlaskForm):
    date = DateField('Date', validators=[DataRequired()], default=datetime.today)
    account_id = SelectField('Account Name', choices=[], coerce=int, validators=[DataRequired()])
    description = TextAreaField('Description', validators=[DataRequired()])
    debit = FloatField('Debit', default=0.0)
    credit = FloatField('Credit', default=0.0)
    attachment = FileField('Attach File',
                           validators=[FileAllowed(['pdf', 'jpg', 'png', 'doc', 'docx'], 'PDF, JPG, PNG, DOC only!')])
    submit = SubmitField('Save Entry')


class HorizontalJournalEntryForm(FlaskForm):
    entries = FieldList(FormField(JournalLineForm), min_entries=1, max_entries=20)
    submit = SubmitField('Save All Entries')