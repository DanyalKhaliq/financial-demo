from typing import Dict, Text, Any, List, Union, Optional
import logging
from rasa_sdk import Tracker, Action
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.forms import FormAction, REQUESTED_SLOT
from rasa_sdk.events import (
    SlotSet,
    EventType,
    ActionExecuted,
    SessionStarted,
    Restarted,
    FollowupAction,
)
from actions.parsing import (
    parse_duckling_time_as_interval,
    parse_duckling_time,
    get_entity_details,
    parse_duckling_currency,
)
from actions.profile import create_mock_profile
from dateutil import parser

logger = logging.getLogger(__name__)


##def custom_request_next_slot(
##    form,
##    dispatcher: "CollectingDispatcher",
##    tracker: "Tracker",
##    domain: Dict[Text, Any],
##) -> Optional[List[EventType]]:
##    """Requests the next slot and utter template if needed,
##    else returns None"""
##    for slot in form.required_slots(tracker):
##        if form._should_request_slot(tracker, slot):
##            logger.debug(f"Request next slot '{slot}'")
##            dispatcher.utter_message(
##                template=f"utter_ask_{form.name()}_{slot}", **tracker.slots
##            )
##            return [SlotSet(REQUESTED_SLOT, slot)]
##
##    return None


class ActionPayCC(Action):
    """Pay credit card..."""

    def name(self) -> Text:
        """Unique identifier of the action"""
        return "action_pay_cc"

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict]:
        """Executes the action"""
        account_balance = float(tracker.get_slot("account_balance"))
        credit_card = tracker.get_slot("credit_card")
        cc_balance = tracker.get_slot("credit_card_balance")
        payment_amount = float(tracker.get_slot("payment_amount"))
        amount_transferred = float(tracker.get_slot("amount_transferred"))

        if tracker.get_slot("confirm") == 'yes':
            cc_balance[credit_card.lower()]["current balance"] -= payment_amount
            account_balance = account_balance - payment_amount
            dispatcher.utter_message(template="utter_cc_pay_scheduled")

            return [
                SlotSet("credit_card", None),
                SlotSet("payment_amount", None),
                SlotSet("confirm", None),
                SlotSet("time", None),
                SlotSet("time_formatted", None),
                SlotSet("start_time", None),
                SlotSet("end_time", None),
                SlotSet("start_time_formatted", None),
                SlotSet("end_time_formatted", None),
                SlotSet("grain", None),
                SlotSet("amount_of_money", None),
                SlotSet("number", None),
                SlotSet(
                    "amount_transferred",
                    amount_transferred + payment_amount,
                ),
                SlotSet("account_balance", f"{account_balance:.2f}"),
                SlotSet("credit_card_balance", cc_balance),
            ]
        else:
            dispatcher.utter_message(template="utter_cc_pay_cancelled")

        return [
            SlotSet("credit_card", None),
            SlotSet("payment_amount", None),
            SlotSet("confirm", None),
            SlotSet("time", None),
            SlotSet("time_formatted", None),
            SlotSet("start_time", None),
            SlotSet("end_time", None),
            SlotSet("start_time_formatted", None),
            SlotSet("end_time_formatted", None),
            SlotSet("grain", None),
            SlotSet("amount_of_money", None),
            SlotSet("number", None),
        ]


class ValidatePayCCForm(Action):
    """Validates Pay credit card form slots..."""

    def name(self) -> Text:
        """Unique identifier of the form"""
        return "validate_cc_payment_form"

    async def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict
    ) -> List[EventType]:
        """Custom validates the filled slots

        TODO 1: Filling the slot payment_amount from entity amount-of-money
        EG. I want to pay 100 dollars on my emblem credit card on Sunday
        https://www.notion.so/rasa/Feedback-on-2-0-4574eaacc0764967ac0b8b82fbc72904#704ed937b4854e6dab1ab9e93e91930f
        
        TODO 2: Figure out why this is not working:
        pay emblem card tomorrow
        -> bot does not ask for date
        -> but date is not properly filled either...
        It results in: 
        Would you like to schedule a payment of $100 towards your emblem account for None?
        """
        extracted_slots: Dict[Text, Any] = tracker.form_slots_to_validate()

        for slot, value in list(extracted_slots.items()):
            validate_func = getattr(self, f"validate_{slot}", lambda *x: {slot: value})
            #
            # The custom validation methods returns a dictionary, with:
            # - the value of the slot, possibly modified, and 'None' if invalid
            # - additional slots that need to be set
            validation_output = await validate_func(value, dispatcher, tracker, domain)

            extracted_slots.update(validation_output)

        # Return SlotSet events that set the slots to the validated values
        return [SlotSet(slot, value) for slot, value in extracted_slots.items()]

    async def validate_payment_amount(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validates payment amount value."""
        credit_card = tracker.get_slot("credit_card")
        cc_balance = tracker.get_slot("credit_card_balance")
        account_balance = float(tracker.get_slot("account_balance"))
        try:
            entity = get_entity_details(
                tracker, "amount-of-money"
            ) or get_entity_details(tracker, "number")
            amount_currency = parse_duckling_currency(entity)
            if not amount_currency:
                raise (TypeError)
            if account_balance < float(amount_currency.get("amount_of_money")):
                dispatcher.utter_message(template="utter_insufficient_funds")
                return {"payment_amount": None}
            return amount_currency
        except (TypeError, AttributeError):
            pass
        if value and value.lower() in cc_balance.get(credit_card.lower()):
            key = value.lower()
            amount = cc_balance.get(credit_card.lower()).get(key)
            amount_type = f" (your {key})"

            if account_balance < float(amount):
                dispatcher.utter_message(template="utter_insufficient_funds")
                return {"payment_amount": None}
            return {
                "payment_amount": f"{amount:.2f}",
                "payment_amount_type": amount_type,
                "currency": "$",
            }

        else:
            dispatcher.utter_message(template="utter_no_payment_amount")
            return {"payment_amount": None}

    async def validate_credit_card(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validates credit_card value."""
        cc_balance = tracker.get_slot("credit_card_balance")
        if value and value.lower() in list(cc_balance.keys()):
            return {"credit_card": value.title()}
        else:
            dispatcher.utter_message(template="utter_no_creditcard")
            return {"credit_card": None}

    async def validate_time(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validates time value."""
        timeentity = get_entity_details(tracker, "time")
        parsedtime = parse_duckling_time(timeentity)
        if not parsedtime:
            dispatcher.utter_message(template="utter_no_transactdate")
            return {"time": None}
        return parsedtime
    
    async def validate_confirm(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validates confirm value."""
        if value in ["yes", "no"]:
            return {"confirm": value}
        else:
            return {"confirm": None}    


class TransactSearchForm(FormAction):
    """Transaction search form"""

    def name(self) -> Text:
        """Unique identifier of the form"""
        return "transact_search_form"

    ##    def request_next_slot(
    ##        self,
    ##        dispatcher: "CollectingDispatcher",
    ##        tracker: "Tracker",
    ##        domain: Dict[Text, Any],
    ##    ) -> Optional[List[EventType]]:
    ##
    ##        return custom_request_next_slot(self, dispatcher, tracker, domain)

    @staticmethod
    def required_slots(tracker: Tracker) -> List[Text]:
        """A list of required slots that the form has to fill"""
        return ["search_type", "time"]

    def slot_mappings(self) -> Dict[Text, Union[Dict, List[Dict]]]:
        """A dictionary to map required slots to
        - an extracted entity
        - intent: value pairs
        - a whole message
        or a list of them, where a first match will be picked"""
        return {
            "search_type": [
                self.from_trigger_intent(intent="search_transactions", value="spend"),
                self.from_trigger_intent(intent="check_earnings", value="deposit"),
            ],
        }

    def validate_vendor_name(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validates vendor_name value."""
        if value and value.lower() in tracker.get_slot("vendor_list"):
            return {"vendor_name": value}
        else:
            dispatcher.utter_message(template="utter_no_vendor_name")
            return {"vendor_name": None}

    def validate_time(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validates time value."""
        timeentity = get_entity_details(tracker, "time")
        parsedinterval = parse_duckling_time_as_interval(timeentity)
        if not parsedinterval:
            dispatcher.utter_message(template="utter_no_transactdate")
            return {"time": None}

        return parsedinterval

    def submit(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict]:
        """Defines what the form has to do
        after all required slots are filled"""
        search_type = tracker.get_slot("search_type")
        transaction_history = tracker.get_slot("transaction_history")
        transactions_subset = transaction_history.get(search_type, {})
        vendor = tracker.get_slot("vendor_name")

        if vendor:
            transactions = transactions_subset.get(vendor.lower())
            vendor = f" with {vendor}"
        else:
            transactions = [v for k in list(transactions_subset.values()) for v in k]
            vendor = ""

        start_time = parser.isoparse(tracker.get_slot("start_time"))
        end_time = parser.isoparse(tracker.get_slot("end_time"))

        for i in range(len(transactions) - 1, -1, -1):
            transaction = transactions[i]
            transaction_date = parser.isoparse(transaction.get("date"))

            if transaction_date < start_time or transaction_date > end_time:
                transactions.pop(i)

        numtransacts = len(transactions)
        total = sum([t.get("amount") for t in transactions])
        slotvars = {
            "total": f"{total:.2f}",
            "numtransacts": numtransacts,
            "start_time_formatted": tracker.get_slot("start_time_formatted"),
            "end_time_formatted": tracker.get_slot("end_time_formatted"),
            "vendor_name": vendor,
        }

        dispatcher.utter_message(
            template=f"utter_searching_{search_type}_transactions", **slotvars
        )
        dispatcher.utter_message(
            template=f"utter_found_{search_type}_transactions", **slotvars
        )

        return [
            SlotSet("time", None),
            SlotSet("time_formatted", None),
            SlotSet("start_time", None),
            SlotSet("end_time", None),
            SlotSet("start_time_formatted", None),
            SlotSet("end_time_formatted", None),
            SlotSet("grain", None),
            SlotSet("search_type", None),
            SlotSet("vendor_name", None),
        ]


class TransferForm(FormAction):
    """Transfer money form..."""

    def name(self) -> Text:
        """Unique identifier of the form"""
        return "transfer_form"

    ##    def request_next_slot(
    ##        self,
    ##        dispatcher: "CollectingDispatcher",
    ##        tracker: "Tracker",
    ##        domain: Dict[Text, Any],
    ##    ) -> Optional[List[EventType]]:
    ##
    ##        return custom_request_next_slot(self, dispatcher, tracker, domain)

    @staticmethod
    def required_slots(tracker: Tracker) -> List[Text]:
        """A list of required slots that the form has to fill"""
        return ["PERSON", "amount_of_money", "confirm"]

    def slot_mappings(self) -> Dict[Text, Union[Dict, List[Dict]]]:
        """A dictionary to map required slots to
        - an extracted entity
        - intent: value pairs
        - a whole message
        or a list of them, where a first match will be picked"""
        return {
            "amount_of_money": [
                self.from_entity(entity="amount-of-money"),
                self.from_entity(entity="number"),
            ],
            "confirm": [
                self.from_intent(value=True, intent="affirm"),
                self.from_intent(value=False, intent="deny"),
            ],
        }

    def validate_PERSON(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validates PERSON value."""
        name = value.title() if value else None
        known_recipients = tracker.get_slot("known_recipients")
        first_names = [name.split()[0] for name in known_recipients]
        if name in known_recipients:
            return {"PERSON": name}
        elif name in first_names:
            index = first_names.index(name)
            fullname = known_recipients[index]
            return {"PERSON": fullname}
        else:
            dispatcher.utter_message(template="utter_unknown_recipient")
            return {"PERSON": None}

    def validate_amount_of_money(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validates amount_of_money value."""
        account_balance = float(tracker.get_slot("account_balance"))
        try:
            entity = get_entity_details(
                tracker, "amount-of-money"
            ) or get_entity_details(tracker, "number")
            amount_currency = parse_duckling_currency(entity)
            if not amount_currency:
                raise (TypeError)
            if account_balance < float(amount_currency.get("amount_of_money")):
                dispatcher.utter_message(template="utter_insufficient_funds")
                return {"amount_of_money": None}
            return amount_currency
        except (TypeError, AttributeError):
            dispatcher.utter_message(template="utter_no_payment_amount")
            return {"amount_of_money": None}

    def submit(self, dispatcher, tracker, domain):
        """Defines what the form has to do
        after all required slots are filled"""
        if tracker.get_slot("confirm"):
            amount_of_money = float(tracker.get_slot("amount_of_money"))
            account_balance = float(tracker.get_slot("account_balance"))

            updated_account_balance = account_balance - amount_of_money

            dispatcher.utter_message(template="utter_transfer_complete")

            amount_transferred = tracker.get_slot("amount_transferred")
            return [
                SlotSet("PERSON", None),
                SlotSet("amount_of_money", None),
                SlotSet("confirm", None),
                SlotSet("amount_transferred", amount_transferred + amount_of_money),
                SlotSet("account_balance", f"{updated_account_balance:.2f}"),
            ]
        else:
            dispatcher.utter_message(template="utter_transfer_cancelled")
            return [
                SlotSet("PERSON", None),
                SlotSet("amount_of_money", None),
                SlotSet("confirm", None),
            ]


class ActionAccountBalance(Action):
    def name(self):
        """Unique identifier of the action"""
        return "action_account_balance"

    def run(self, dispatcher, tracker, domain):
        """Executes the custom action"""
        account_balance = float(tracker.get_slot("account_balance"))
        amount = tracker.get_slot("amount_transferred")
        if amount:
            amount = float(tracker.get_slot("amount_transferred"))
            init_account_balance = account_balance + amount
            dispatcher.utter_message(
                template="utter_changed_account_balance",
                init_account_balance=f"{init_account_balance:.2f}",
                account_balance=f"{account_balance:.2f}",
            )
            return [SlotSet("payment_amount", None)]
        else:
            dispatcher.utter_message(
                template="utter_account_balance",
                init_account_balance=f"{account_balance:.2f}",
            )
            return [SlotSet("payment_amount", None)]


class ActionCreditCardBalance(Action):
    def name(self):
        """Unique identifier of the action"""
        return "action_credit_card_balance"

    def run(self, dispatcher, tracker, domain):
        """Executes the custom action"""
        credit_card_balance = tracker.get_slot("credit_card_balance")
        credit_card = tracker.get_slot("credit_card")

        if credit_card and credit_card.lower() in credit_card_balance:
            current_balance = credit_card_balance[credit_card.lower()][
                "current balance"
            ]
            dispatcher.utter_message(
                template="utter_credit_card_balance",
                credit_card=credit_card.title(),
                amount_of_money=f"{current_balance:.2f}",
            )
            return [SlotSet("credit_card", None)]
        else:
            for credit_card in credit_card_balance.keys():
                current_balance = credit_card_balance[credit_card]["current balance"]
                dispatcher.utter_message(
                    template="utter_credit_card_balance",
                    credit_card=credit_card.title(),
                    amount_of_money=f"{current_balance:.2f}",
                )

            return []


class ActionRecipients(Action):
    def name(self):
        """Unique identifier of the action"""
        return "action_recipients"

    def run(self, dispatcher, tracker, domain):
        """Executes the custom action"""
        recipients = tracker.get_slot("known_recipients")
        formatted_recipients = "\n" + "\n".join(
            [f"- {recipient}" for recipient in recipients]
        )
        dispatcher.utter_message(
            template="utter_recipients",
            formatted_recipients=formatted_recipients,
        )
        return []


class ActionSessionStart(Action):
    def name(self) -> Text:
        """Unique identifier of the action"""
        return "action_session_start"

    @staticmethod
    def _slot_set_events_from_tracker(
        tracker: "Tracker",
    ) -> List["SlotSet"]:
        """Fetches SlotSet events from tracker and carries over keys and values"""
        return [
            SlotSet(
                key=event.get("name"),
                value=event.get("value"),
            )
            for event in tracker.events
            if event.get("event") == "slot"
        ]

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[EventType]:
        """Executes the custom action"""
        # the session should begin with a `session_started` event
        events = [SessionStarted()]

        events.extend(self._slot_set_events_from_tracker(tracker))

        # create mock profile
        user_profile = create_mock_profile()

        # initialize slots from mock profile
        for key, value in user_profile.items():
            if value is not None:
                events.append(SlotSet(key=key, value=value))

        # an `action_listen` should be added at the end
        events.append(ActionExecuted("action_listen"))

        return events


class ActionRestart(Action):
    def name(self) -> Text:
        """Unique identifier of the action"""
        return "action_restart"

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[EventType]:
        """Executes the custom action"""
        return [Restarted(), FollowupAction("action_session_start")]
