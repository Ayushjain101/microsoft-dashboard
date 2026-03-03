# Step 1: Setup Microsoft panel

## 1.1: Log in to panel.

	Log in to panel admin.microsoft.com
	If it forces to setup a mfa, setup one use the authenticator extension.
	Do not use the microsoft authenticatior for mfa setup.

## 1.2: Disable forced MFA for organization.

	Go to entra.microsoft.com
	Go to Overview > Properties
	Scroll down to find Security defaults -> Manage security defaults
	Set Security defaults to disabled and save.

	Go into Authentication methods > Registration campaign
	Update State to Disabled.
	Go into Authentication methods > Settings
	Set System-preferred multifactor authentication State to disabled.

## 1.3: Delete MFA of admin user

	Go to myaccount.microsoft.com
	Under My Account -> Security info
	Delete the TOTP and recovery mail if any.

## 1.4: Turn on SMTP AUTH for organization.

	Go to admin.exchange.microsoft.com > Settings > Mail Flow
	Under Security section 
	Uncheck the "Turn off SMTP AUTH protocol for your organization" and save.

## 1.5: Assign a license to the admin user.
    
    Go to billing > Lincenses
    Click License > Assign License 
	Assign the one available license to admin@ user.


# Step 2: Add domain/s to the panel

## 2.1: Add domain/s manually.

>[!WARNING] Make sure the domain you are adding is present in Cloudflare

	Go to admin.cloud.microsoft -> Settings -> Domains
	Click Add domain, enter the domain and click "Use the domain".
	Click on verify (Make sure sign in to CLoudflare is seleted).
	Login in to cloudflare to add the verification record.
	After the domain is verified successfully.
	Click continue (Make sure Let microsoft add your DNS records is selected).
	Check "Exchange and Exchange Online Protection" option.
	Under Advanced options make sure DKIM is checked too.
	Click on continue/Add and authorise the addtion of records in Cloudflare.
	Once all the records are added Domain Setup is complete.

## 2.2: Enable DKIM for domain/s.

	Go to https://security.microsoft.com/dkimv2
	Make sure the Status for that domain is Valid and Toggle is Enabled.
	If not click on the toggle to enable it.
	It might ask to create dkim key just click on create and toggle enable.

## 2.3: Add DMARC record.

	Use this N8N workflow to add the record 
    
    N8N creditials: 
    username: gautam@icedautomations.com
    password: Work@2002	

```url
https://n8n.icedautomation.com/workflow/mW6P1NE8irPTRN3Y)
```

## 3.1: Generate the JSON (Process can be improved)

To generate the JSON use this below format to number of domains and user names accrodingly.

 {
    "first_name": "Vincent",
    "second_name": "Declercq",
    "password": "Dalton@Iced#4904",
    "username": "vincent@godaltonhq.co",
    "domain": "godaltonhq.co"
}

Once you generate required users in the above format, go to this n8n automation

https://n8n.icedautomation.com/workflow/eXgZDaTirAxDj6c1

1. Change the 3 values from excel sheet 
 1. cookie (login -> admin.microsoft.com and through the cookie-editor (extension) click on export and copy the HeaderString)
 2. exchange_cookie (login -> admin.exchange.microsoft.com and through the cookie-editor (extension) click on export and copy the HeaderString)
 3. data (these are array of objects which you generated)

Once you update the values, run the automation, it will create all users in the tenants and time is based on users count.

## 3.2: Upload it to instantly

1. Once you can see all users and export from admin.microsoft.com all users 
2. Make sure add them 'emails.txt' and 'passwords.txt'
3. run the automation using this below commands 
 
>[!WARNING] Make sure to allow first one users for one tenant compulsory and give grant permissions for that tenant users
For that add one user manualy to instantly for tenant and give grant permission and rest will add into emails.txt 

python3 addToInstantly.py 'Instantlyemail' 'Instantlypassword' emails.txt passwords.txt 'WorkspaceName' -> (for gsuit users)
python3 addToInstantlyMS.py 'Instantlyemail' 'Instantlypassword' emails.txt passwords.txt 'WorkspaceName' -> (for msuit users)

This is complete process of creating room mailboxes in microsft admin and uploading into the Instantly.